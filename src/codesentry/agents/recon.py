"""ReconAgent（agent.md §7.2）：语言/框架/入口点 + 增量模式 diff 可达闭包。

M3 版：扩展 M1 detect_languages；框架按特征文件；入口点按装饰器/路由特征；
diff 闭包（GraphRAG 路线 A 前置）用 M2 chunker 抽 call_refs 建 python 调用图并 BFS。
"""

import os
from pathlib import Path

from codesentry.scan_orchestrator import detect_languages

FRAMEWORK_SIGS = {
    "python": {
        "requirements.txt": None,
        "pyproject.toml": None,
    },
    "javascript": {"package.json": None},
    "java": {"pom.xml": "maven", "build.gradle": "gradle"},
    "go": {"go.mod": None},
    "php": {"composer.json": None},
}

_ENTRY_HINTS = ("Router", "route", "@app.", "Handler", "Controller", "Blueprint")


def detect_frameworks(repo: str) -> list[str]:
    found: list[str] = []
    for sigs in FRAMEWORK_SIGS.values():
        if not isinstance(sigs, dict):  # 防御：sigs 结构应为 dict
            continue
        for fname, fw_name in sigs.items():
            if (Path(repo) / fname).exists():
                found.append(fw_name or fname)
    return sorted(set(found))


def detect_entry_points(repo: str, lang_list: list[str]) -> list[str]:
    hits: list[str] = []
    exts = {".py"}
    for root, _dirs, files in os.walk(repo):
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext in exts:
                p = Path(root) / name
                try:
                    if any(h in p.read_text(encoding="utf-8", errors="replace")[:4000] for h in _ENTRY_HINTS):
                        hits.append(str(p.relative_to(repo)))
                except OSError:
                    continue
    return hits[:20]


def build_profile(repo: str) -> dict:
    langs = detect_languages(repo)
    return {
        "languages": langs,
        "frameworks": detect_frameworks(repo),
        "entry_points": detect_entry_points(repo, langs) if "python" in langs else [],
    }


# ---- 增量审计：diff 可达闭包（FR-10；GraphRAG 路线 A 的闭包算法落地）----

def _python_callgraph(repo: str) -> dict[str, set[str]]:
    """简化调用图：caller 函数 -> callee 名集合（用 M2 chunker 的 call_refs）。"""
    from codesentry.rag.chunker import chunk_code

    graph: dict[str, set[str]] = {}
    for root, _dirs, files in os.walk(repo):
        for name in files:
            if not name.endswith(".py"):
                continue
            p = Path(root) / name
            try:
                src = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for c in chunk_code(str(p), "python", src):
                if c.symbol_kind != "function":
                    continue
                graph.setdefault(f"{c.path}:{c.symbol_name}", set()).update(c.call_refs)
    return graph


def diff_reachable_closure(repo: str, diff_files: list[str], *, max_hops: int = 4) -> list[str]:
    """从 diff 文件出发沿 python 调用图 BFS 取可达函数闭包（审查重点 5）。

    返回闭包内文件列表（带 diff_files 本身）。非 python 仓库退化为 diff_files。
    """
    def _norm(p: str) -> str:
        # 统一为绝对路径字符串，号栈（symlink/./ 归一在 resolve）
        pp = Path(p)
        if not pp.is_absolute():
            pp = Path(repo) / p
        return str(pp.resolve())

    diff_abs = {(_norm(df), df) for df in diff_files}

    langs = detect_languages(repo)
    if not any(l in ("python",) for l in langs):
        return list(diff_files)
    graph = _python_callgraph(repo)
    # 起 frontier：diff 文件内定义的函数
    frontier: list[str] = []
    for node in graph:
        path_part = node.rsplit(":", 1)[0]
        p_abs = str(Path(path_part).resolve())
        if any(p_abs == a for a, _df in diff_abs):
            frontier.append(node)
    seen: set[str] = set(frontier)
    hops = 0
    while frontier and hops < max_hops:
        nxt: list[str] = []
        for node in frontier:
            for callee in graph.get(node, ()):  # BFS 顺着 call_refs
                callee_short = callee.split(".")[-1]
                for n in graph:
                    if n.endswith(":" + callee_short) and n not in seen:
                        seen.add(n)
                        nxt.append(n)
        frontier = nxt
        hops += 1
    closure_files = sorted({Path(n.rsplit(":", 1)[0]).name for n in seen if ":" in n})
    out = list(dict.fromkeys([*diff_files, *closure_files]))
    return out


def run_recon(state: dict) -> dict:
    """节点实现（graph 节点签名：state -> state 更新 dict）。"""
    repo = state["repo_path"]
    profile = build_profile(repo)
    update: dict = {"profile": profile, "phase": "scan"}
    if state.get("diff_scope"):
        ds = state["diff_scope"]
        closure = diff_reachable_closure(repo, ds.get("files", []))
        update["diff_scope"] = {**ds, "closure": closure}
    return update
