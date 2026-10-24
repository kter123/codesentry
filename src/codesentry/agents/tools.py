"""Agent 工具循环（M6.6）：read_source / search_code / read_evidence。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path


def _parse_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def build_tools(state: dict) -> dict[str, Callable]:
    repo = Path(str(state.get("repo_path") or ".")).resolve()
    project = str(repo)

    def read_source(path: str, start: int = 1, end: int = 120) -> str:
        target = (repo / str(path)).resolve()
        if repo not in target.parents and target != repo:
            return "DENIED: path escapes repo"
        try:
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as e:
            return f"ERROR: {e}"
        start = max(1, int(start))
        end = min(len(lines), max(start, int(end)))
        return "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))[:8000]

    def search_code(query: str, top_k: int = 3) -> str:
        try:
            from codesentry.rag.embedding import embed_texts
            from codesentry.rag.retrieve import hybrid_search

            vec = embed_texts([str(query)])[0]
            rows = hybrid_search("code", str(query), vec, top_k=int(top_k))
            return json.dumps(rows, ensure_ascii=False)[:8000]
        except Exception as e:  # noqa: BLE001
            return f"ERROR: {e}"

    def read_evidence(key: str = "") -> str:
        evd = state.get("evidence") or {}
        if key:
            return json.dumps(evd.get(str(key), {}), ensure_ascii=False)[:8000]
        return json.dumps(evd, ensure_ascii=False)[:8000]

    def graph_search(query: str, kinds: list[str] | None = None, limit: int = 20) -> str:
        try:
            from codesentry.db.pool import get_conn

            sql = ("SELECT node_key, kind, name, path, start_line, end_line FROM graph_nodes"
                   " WHERE project=%s AND (name ILIKE %s OR qualified_name ILIKE %s)")
            params: list = [project, f"%{query}%", f"%{query}%"]
            if kinds:
                sql += " AND kind = ANY(%s)"
                params.append(list(kinds))
            sql += " ORDER BY (kind='endpoint') DESC, (kind='function') DESC LIMIT %s"
            params.append(max(1, min(int(limit), 100)))
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
            return json.dumps([
                {"key": r[0], "kind": r[1], "name": r[2], "path": r[3],
                 "start": r[4], "end": r[5]} for r in rows
            ], ensure_ascii=False)[:8000]
        except Exception as e:  # noqa: BLE001
            return f"ERROR: {e}"

    def graph_node(key: str) -> str:
        try:
            from codesentry.rag.graph_query import node

            found = node(project, str(key))
            if not found:
                return "NOT FOUND"
            body = ""
            try:
                lines = (repo / found["path"]).read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                start = max(1, int(found["start"]))
                end = min(len(lines), int(found["end"]))
                body = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))[:6000]
            except OSError:
                pass
            return json.dumps({**found, "source": body}, ensure_ascii=False)[:8000]
        except Exception as e:  # noqa: BLE001
            return f"ERROR: {e}"

    def graph_neighbors(key: str, depth: int = 1, edge_kinds: list[str] | None = None) -> str:
        try:
            from codesentry.rag.graph_query import neighbors

            result = neighbors(project, str(key), depth=int(depth), edge_kinds=edge_kinds)
            return json.dumps(result, ensure_ascii=False)[:8000]
        except Exception as e:  # noqa: BLE001
            return f"ERROR: {e}"

    def graph_paths(src: str, dst: str, max_depth: int = 6) -> str:
        try:
            from codesentry.rag.graph_query import paths

            return json.dumps(paths(project, str(src), str(dst), max_depth=int(max_depth)),
                              ensure_ascii=False)[:8000]
        except Exception as e:  # noqa: BLE001
            return f"ERROR: {e}"

    def graph_entrypoints(permission: str = "") -> str:
        try:
            from codesentry.rag.graph_query import entrypoints

            rows = entrypoints(project, permission or None)
            return json.dumps(rows, ensure_ascii=False)[:8000]
        except Exception as e:  # noqa: BLE001
            return f"ERROR: {e}"

    def kb_search(query: str, top_k: int = 5) -> str:
        try:
            from codesentry.rag.kb_ops import search

            return json.dumps(search(query, top_k=int(top_k)), ensure_ascii=False)[:8000]
        except Exception as e:  # noqa: BLE001
            return f"ERROR: {e}"

    def vuln_cases(query: str, cwe: int | None = None, limit: int = 5) -> str:
        try:
            from codesentry.rag.experience import search_vuln_cases

            return json.dumps(
                search_vuln_cases(query, cwe=cwe, limit=int(limit)), ensure_ascii=False
            )[:8000]
        except Exception as e:  # noqa: BLE001
            return f"ERROR: {e}"

    def audit_patterns(query: str, cwe: int | None = None, limit: int = 5) -> str:
        try:
            from codesentry.rag.experience import search_patterns

            return json.dumps(
                search_patterns(query, cwe=cwe, limit=int(limit)), ensure_ascii=False
            )[:8000]
        except Exception as e:  # noqa: BLE001
            return f"ERROR: {e}"

    def scan_strategies(query: str, limit: int = 3) -> str:
        try:
            from codesentry.rag.experience import search_strategies

            return json.dumps(
                search_strategies(query, limit=int(limit)), ensure_ascii=False
            )[:8000]
        except Exception as e:  # noqa: BLE001
            return f"ERROR: {e}"

    def engine_hints() -> str:
        return json.dumps(state.get("engine_hints") or [], ensure_ascii=False)[:8000]

    return {
        "read_source": read_source,
        "search_code": search_code,
        "read_evidence": read_evidence,
        "graph_search": graph_search,
        "graph_node": graph_node,
        "graph_neighbors": graph_neighbors,
        "graph_paths": graph_paths,
        "graph_entrypoints": graph_entrypoints,
        "kb_search": kb_search,
        "vuln_cases": vuln_cases,
        "audit_patterns": audit_patterns,
        "scan_strategies": scan_strategies,
        "engine_hints": engine_hints,
    }


def run_tool_loop(
    llm,
    system: str,
    user: str,
    *,
    tools: dict[str, Callable] | None,
    max_iterations: int = 8,
    model_role: str = "deep",
) -> tuple[str, list[dict]]:
    """LLM 可返回 {"tool_calls":[...]} 请求工具；最多 max_iterations 轮。"""
    trace: list[dict] = []
    context = user
    text = ""
    for iteration in range(max(1, int(max_iterations or 1))):
        text = llm.complete(system, context, model_role=model_role)
        data = _parse_json(text)
        calls = (data or {}).get("tool_calls") if isinstance(data, dict) else None
        if not calls or not tools:
            trace.append({"iteration": iteration + 1, "final": True})
            break
        results = []
        for call in list(calls)[:3]:
            if not isinstance(call, dict):
                continue
            name = str(call.get("tool") or "")
            args = call.get("args") or {}
            fn = tools.get(name)
            if fn is None:
                results.append(f"{name}: unknown tool")
                continue
            try:
                out = fn(**args) if isinstance(args, dict) else fn()
            except Exception as e:  # noqa: BLE001
                out = f"ERROR: {e}"
            out_s = str(out)[:4000]
            trace.append({"iteration": iteration + 1, "tool": name, "args": args,
                          "output_preview": out_s[:500]})
            results.append(f"[tool {name}] {out_s}")
        context = user + "\n\n## 工具结果\n" + "\n\n".join(results)
    return text, trace
