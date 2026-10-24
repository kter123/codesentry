"""代码图构建（G1）：按文件增量解析、跨文件调用解析、污点边与接口资产。"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from codesentry.rag.extractors import ExtractResult, extract, lang_for_path

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "vendor", "dist", "build", "target",
    ".venv", "venv", "env", "__pycache__", ".idea", ".gradle", "bin", "obj",
    "Pods", "coverage", ".next", "out", ".mypy_cache", ".pytest_cache", ".ruff_cache",
}
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES = 20000

_PY_BUILTINS = {
    "len", "print", "str", "int", "float", "bool", "dict", "list", "set", "tuple",
    "range", "enumerate", "zip", "map", "filter", "sum", "min", "max", "abs",
    "sorted", "reversed", "isinstance", "issubclass", "getattr", "setattr", "hasattr",
    "super", "type", "id", "repr", "format", "any", "all", "iter", "next", "round",
}
_TAINT_ARG_HINTS = ("request", "req.", "params", "args", "body", "query", "input", "ctx.")


@dataclass
class BuildStats:
    files_total: int = 0
    files_parsed: int = 0
    files_unchanged: int = 0
    files_deleted: int = 0
    files_failed: int = 0
    nodes: int = 0
    edges: int = 0
    endpoints: int = 0
    unresolved_calls: int = 0
    duration_ms: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "files_total": self.files_total,
            "files_parsed": self.files_parsed,
            "files_unchanged": self.files_unchanged,
            "files_deleted": self.files_deleted,
            "files_failed": self.files_failed,
            "nodes": self.nodes,
            "edges": self.edges,
            "endpoints": self.endpoints,
            "unresolved_calls": self.unresolved_calls,
            "duration_ms": self.duration_ms,
            "errors": self.errors[:20],
        }


def build_graph(
    repo_path: str,
    *,
    project: str | None = None,
    mode: str = "full",
    changed_files: list[str] | None = None,
    max_files: int = MAX_FILES,
) -> dict:
    import time

    started = time.monotonic()
    from codesentry.control.bootstrap import ensure_control_schema

    ensure_control_schema()
    repo = Path(repo_path).resolve()
    project = project or str(repo)
    stats = BuildStats()

    current = _scan_files(repo, max_files=max_files, stats=stats)
    baseline = _load_baseline(project)
    changed = _diff_files(current, baseline, mode, changed_files, stats)
    deleted = sorted(set(baseline) - set(current))

    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO graph_builds (project, mode, status, stats) VALUES (%s,%s,'running','{}')"
            " RETURNING id",
            (project, mode),
        )
        build_id = int(cur.fetchone()[0])
        conn.commit()

    parsed: dict[str, ExtractResult] = {}
    with get_conn() as conn, conn.cursor() as cur:
        for path in deleted:
            _delete_file(cur, project, path)
            stats.files_deleted += 1
        cur.execute("DELETE FROM graph_files WHERE project=%s AND path = ANY(%s)",
                    (project, deleted))

        _upsert_node(cur, project, build_id, _repo_node(project, repo))
        for rel in changed:
            lang = lang_for_path(rel)
            if not lang:
                continue
            full = repo / rel
            try:
                source = full.read_text(encoding="utf-8", errors="replace")
                result = extract(rel, lang, source)
            except Exception as exc:  # noqa: BLE001
                stats.files_failed += 1
                stats.errors.append(f"{rel}: {str(exc)[:160]}")
                _delete_file(cur, project, rel)
                continue
            parsed[rel] = result
            stats.files_parsed += 1
            _replace_file(cur, project, build_id, rel, result, stats)
            cur.execute(
                "INSERT INTO graph_files (project, path, sha256, lang, build_id, updated_at)"
                " VALUES (%s,%s,%s,%s,%s,now()) ON CONFLICT (project, path) DO UPDATE SET"
                " sha256=EXCLUDED.sha256, lang=EXCLUDED.lang, build_id=EXCLUDED.build_id,"
                " updated_at=now()",
                (project, rel, current[rel], lang, build_id),
            )

        if mode == "full" or changed:
            _resolve_dynamic_edges(cur, project, build_id, parsed, stats)
            _write_endpoints(cur, project, build_id, parsed, stats)
        _cleanup_orphans(cur, project)
        cur.execute("SELECT count(*) FROM graph_nodes WHERE project=%s", (project,))
        stats.nodes = int(cur.fetchone()[0])
        cur.execute("SELECT count(*) FROM graph_edges WHERE project=%s", (project,))
        stats.edges = int(cur.fetchone()[0])
        cur.execute("SELECT count(*) FROM graph_endpoints WHERE project=%s", (project,))
        stats.endpoints = int(cur.fetchone()[0])
        conn.commit()

    stats.duration_ms = int((time.monotonic() - started) * 1000)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE graph_builds SET status='ok', stats=%s WHERE id=%s",
            (json.dumps(stats.as_dict(), ensure_ascii=False), build_id),
        )
        conn.commit()
    return {
        "build_id": build_id, "project": project, "ok": True,
        "stats": stats.as_dict(), "changed": changed, "deleted": deleted,
    }


def _scan_files(repo: Path, *, max_files: int, stats: BuildStats) -> dict[str, str]:
    out: dict[str, str] = {}
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".git")]
        for name in files:
            if len(out) >= max_files:
                stats.errors.append(f"file limit reached: {max_files}")
                return out
            path = Path(root) / name
            rel = str(path.relative_to(repo))
            if lang_for_path(rel) is None:
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
                data = path.read_bytes()
            except OSError:
                continue
            out[rel] = hashlib.sha256(data).hexdigest()
    stats.files_total = len(out)
    return out


def _load_baseline(project: str) -> dict[str, str]:
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT path, sha256 FROM graph_files WHERE project=%s", (project,))
            return {r[0]: r[1] for r in cur.fetchall()}
    except Exception:  # noqa: BLE001
        return {}


def _diff_files(current, baseline, mode, changed_files, stats) -> list[str]:
    if mode == "full" or not baseline:
        return sorted(current)
    if changed_files:
        requested = {c.lstrip("./") for c in changed_files}
        return sorted(p for p in current if p in requested and current[p] != baseline.get(p))
    changed = [p for p, sha in current.items() if baseline.get(p) != sha]
    stats.files_unchanged = len(current) - len(changed)
    return sorted(changed)


def _repo_node(project: str, repo: Path):
    from codesentry.rag.extractors.base import CodeNode

    return CodeNode(
        key=f"repo:{project}", kind="repo", name=repo.name, lang="",
        attrs={"root": str(repo)},
    )


def _replace_file(cur, project: str, build_id: int, path: str, result: ExtractResult,
                  stats: BuildStats) -> None:
    _delete_file(cur, project, path)
    for node in result.nodes:
        _upsert_node(cur, project, build_id, node)
    for edge in result.edges:
        _upsert_edge(cur, project, build_id, edge)
    stats.unresolved_calls += result.unresolved_calls


def _delete_file(cur, project: str, path: str) -> None:
    cur.execute(
        "DELETE FROM graph_edges WHERE project=%s AND ("
        " src_key IN (SELECT node_key FROM graph_nodes WHERE project=%s AND path=%s)"
        " OR dst_key IN (SELECT node_key FROM graph_nodes WHERE project=%s AND path=%s))",
        (project, project, path, project, path),
    )
    cur.execute("DELETE FROM graph_nodes WHERE project=%s AND path=%s", (project, path))
    cur.execute("DELETE FROM graph_endpoints WHERE project=%s AND path=%s", (project, path))


def _upsert_node(cur, project: str, build_id: int, node) -> None:
    cur.execute(
        "INSERT INTO graph_nodes (project, node_key, kind, name, path, qualified_name,"
        " start_line, end_line, lang, attrs, build_id)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (project, node_key) DO UPDATE SET kind=EXCLUDED.kind,"
        " name=EXCLUDED.name, path=EXCLUDED.path, qualified_name=EXCLUDED.qualified_name,"
        " start_line=EXCLUDED.start_line, end_line=EXCLUDED.end_line, lang=EXCLUDED.lang,"
        " attrs=EXCLUDED.attrs, build_id=EXCLUDED.build_id",
        (project, node.key, node.kind, node.name, node.path, node.qualified_name,
         node.start_line, node.end_line, node.lang, json.dumps(node.attrs, ensure_ascii=False),
         build_id),
    )


def _upsert_edge(cur, project: str, build_id: int, edge) -> None:
    cur.execute(
        "INSERT INTO graph_edges (project, src_key, dst_key, kind, provenance, confidence,"
        " attrs, build_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (project, src_key, dst_key, kind) DO UPDATE SET"
        " provenance=EXCLUDED.provenance, confidence=EXCLUDED.confidence,"
        " attrs=EXCLUDED.attrs, build_id=EXCLUDED.build_id",
        (project, edge.src_key, edge.dst_key, edge.kind, edge.provenance,
         float(edge.confidence), json.dumps(edge.attrs, ensure_ascii=False), build_id),
    )


def _resolve_dynamic_edges(cur, project: str, build_id: int, parsed: dict[str, ExtractResult],
                           stats: BuildStats) -> None:
    from codesentry.rag.extractors.base import CodeEdge, CodeNode

    cur.execute(
        "SELECT node_key, kind, name, path, qualified_name, attrs"
        " FROM graph_nodes WHERE project=%s AND kind IN ('function','method')",
        (project,),
    )
    rows = cur.fetchall()
    by_name: dict[str, list[str]] = {}
    by_qual: dict[str, str] = {}
    for key, _kind, name, path, qual, _attrs in rows:
        by_name.setdefault(name, []).append(key)
        if qual:
            by_qual[qual] = key

    cur.execute("SELECT node_key, path, attrs FROM graph_nodes"
                " WHERE project=%s AND kind='file'", (project,))
    files = cur.fetchall()
    path_keys = {r[1]: r[0] for r in files}
    module_index: dict[str, str] = {}
    for p, key in path_keys.items():
        stem = re.sub(r"\.(py|java|js|mjs|cjs|ts|tsx|go|php|c|h|cc|cpp|cxx|hpp|hh)$", "", p)
        module_index[stem] = key
        if stem.endswith("/__init__"):
            module_index[stem[: -len("/__init__")]] = key
        if stem.endswith("/index"):
            module_index[stem[: -len("/index")]] = key

    cur.execute("DELETE FROM graph_edges WHERE project=%s AND kind IN ('calls','imports')",
                (project,))
    for key, _kind, name, path, _qual, attrs in rows:
        for call in (attrs or {}).get("calls") or []:
            callee = str(call.get("callee") or "").strip()
            target = _resolve_call(callee, path, by_name, by_qual)
            if target is None:
                if callee and callee.split(".")[-1] not in _PY_BUILTINS:
                    stats.unresolved_calls += 1
                continue
            if target == key:
                continue
            _upsert_edge(cur, project, build_id, CodeEdge(
                key, target, "calls", provenance="tree_sitter", confidence=0.9,
                attrs={"line": call.get("line")},
            ))
    for path, key, attrs in files:
        for module in (attrs or {}).get("imports") or []:
            target = _resolve_import(str(module), module_index)
            dst = target or f"external:{str(module)[:180]}"
            if not target:
                _upsert_node(cur, project, build_id, CodeNode(
                    key=dst, kind="external", name=str(module)[:180], lang="",
                    attrs={"module": str(module)[:300]},
                ))
            _upsert_edge(cur, project, build_id, CodeEdge(
                key, dst, "imports", confidence=1.0 if target else 0.3,
            ))
    _write_taint_edges(cur, project, build_id, parsed)
    stats.unresolved_calls = min(stats.unresolved_calls, 100000)


def _resolve_call(callee: str, path: str, by_name: dict[str, list[str]],
                  by_qual: dict[str, str]) -> str | None:
    if not callee:
        return None
    name = callee.split(".")[-1].strip("()")
    if callee in by_qual:
        return by_qual[callee]
    candidates = by_name.get(name) or []
    if not candidates:
        return None
    same_file = [c for c in candidates if c.startswith(f"function:{path}#")]
    if same_file:
        return same_file[0]
    if len(candidates) == 1:
        return candidates[0]
    directory = path.rsplit("/", 1)[0] if "/" in path else ""
    same_dir = [
        c for c in candidates
        if _dir_of(c) == directory
    ]
    return same_dir[0] if len(same_dir) == 1 else None


def _dir_of(function_key: str) -> str:
    path = function_key[len("function:"):].split("#", 1)[0]
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _resolve_import(module: str, index: dict[str, str]) -> str | None:
    text = module
    for prefix in ("import ", "from ", "package ", "use "):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    text = text.split(" as ")[0].split(";")[0].strip().strip("\"'")
    candidates = [text.replace(".", "/"), text.replace("\\", "/")]
    if text.startswith(("@", "http")):
        return None
    for cand in candidates:
        for suffix in ("", ".py", ".java", ".js", ".ts", ".tsx", ".go", ".php", ".c", ".h", ".cpp", ".hpp"):
            key = index.get(cand + suffix)
            if key:
                return key
        # Java fully-qualified class: com/x/Y -> find path ending with it
        for p, key in index.items():
            if p.endswith(cand):
                return key
    return None


def _write_taint_edges(cur, project: str, build_id: int, parsed: dict[str, ExtractResult]) -> None:
    from codesentry.rag.extractors.base import CodeEdge, CodeNode

    for rel, result in parsed.items():
        route_funcs = {
            edge.dst_key for edge in result.edges if edge.kind == "routes_to"
        } | {
            edge.src_key for edge in result.edges if edge.kind == "exposes"
        }
        for node in result.nodes:
            if node.kind not in ("function", "method"):
                continue
            sources = node.attrs.get("sources") or []
            sinks = node.attrs.get("sinks") or []
            if not sources and not sinks:
                continue
            sink_texts = [str(s.get("arg_text") or "").lower() for s in sinks]
            is_route = node.key in route_funcs
            kept = [
                src for src in sources
                if is_route or any(_mentions(text, str(src.get("name") or "")) for text in sink_texts)
            ]
            src_keys = []
            for src in kept:
                skey = f"source:{rel}#{node.qualified_name}:{src.get('name')}"
                _upsert_node(cur, project, build_id, CodeNode(
                    key=skey, kind="source", name=str(src.get("name")), path=rel,
                    start_line=int(src.get("line") or 0), end_line=int(src.get("line") or 0),
                    lang=node.lang, attrs={"function": node.key, "source_kind": src.get("kind")},
                ))
                _upsert_edge(cur, project, build_id, CodeEdge(node.key, skey, "contains"))
                src_keys.append(skey)
            if sinks and not src_keys and is_route:
                skey = f"source:{rel}#{node.qualified_name}:request"
                _upsert_node(cur, project, build_id, CodeNode(
                    key=skey, kind="source", name="request", path=rel,
                    start_line=node.start_line, end_line=node.start_line, lang=node.lang,
                    attrs={"function": node.key, "source_kind": "implicit"},
                ))
                _upsert_edge(cur, project, build_id, CodeEdge(node.key, skey, "contains"))
                src_keys.append(skey)
            for sink in sinks:
                line = int(sink.get("line") or 0)
                dkey = f"sink:{rel}#{node.qualified_name}:{sink.get('callee')}@{line}"
                _upsert_node(cur, project, build_id, CodeNode(
                    key=dkey, kind="sink", name=str(sink.get("callee"))[:120], path=rel,
                    start_line=line, end_line=line, lang=node.lang,
                    attrs={"function": node.key, "arg_text": sink.get("arg_text", "")[:400]},
                ))
                _upsert_edge(cur, project, build_id, CodeEdge(node.key, dkey, "contains"))
                arg_text = str(sink.get("arg_text") or "").lower()
                for skey in src_keys:
                    src_name = skey.rsplit(":", 1)[-1]
                    if _mentions(arg_text, src_name) or any(h in arg_text for h in _TAINT_ARG_HINTS):
                        _upsert_edge(cur, project, build_id, CodeEdge(
                            skey, dkey, "taints_to", provenance="heuristic",
                            confidence=0.5, attrs={"line": line},
                        ))
                    elif is_route and arg_text:
                        _upsert_edge(cur, project, build_id, CodeEdge(
                            skey, dkey, "taints_to", provenance="heuristic",
                            confidence=0.35, attrs={"line": line, "reason": "same_function"},
                        ))


def _mentions(text: str, name: str) -> bool:
    if not name:
        return False
    return re.search(rf"(?<![\w.]){re.escape(name.lower())}(?![\w])", text) is not None


def _write_endpoints(cur, project: str, build_id: int, parsed: dict[str, ExtractResult],
                     stats: BuildStats) -> None:
    for result in parsed.values():
        for ep in result.endpoints:
            cur.execute(
                "INSERT INTO graph_endpoints (project, endpoint_key, method, route, permission,"
                " path, line, evidence, mismatch, attrs, build_id)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)"
                " ON CONFLICT (project, endpoint_key) DO UPDATE SET method=EXCLUDED.method,"
                " route=EXCLUDED.route, permission=EXCLUDED.permission, path=EXCLUDED.path,"
                " line=EXCLUDED.line, evidence=EXCLUDED.evidence, mismatch=EXCLUDED.mismatch,"
                " attrs=EXCLUDED.attrs, build_id=EXCLUDED.build_id",
                (project, ep["key"], ep.get("method", ""), ep.get("route", ""),
                 ep.get("permission", "其他"), ep.get("path", ""), int(ep.get("line") or 0),
                 ep.get("evidence", ""), bool(ep.get("mismatch")), "{}", build_id),
            )
            stats.endpoints += 1


def _cleanup_orphans(cur, project: str) -> None:
    cur.execute(
        "DELETE FROM graph_nodes WHERE project=%s AND kind IN ('external','module')"
        " AND node_key NOT IN (SELECT src_key FROM graph_edges WHERE project=%s)"
        " AND node_key NOT IN (SELECT dst_key FROM graph_edges WHERE project=%s)",
        (project, project, project),
    )
