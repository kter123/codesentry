"""引擎结果 → 图增量（GraphDelta），不直接生成 finding。"""

from __future__ import annotations

from pathlib import Path

from codesentry.rag.extractors.base import CodeEdge, CodeNode


def hints_from_engine_results(results: list) -> list[dict]:
    hints: list[dict] = []
    for result in results:
        if getattr(result, "status", "") != "ok":
            continue
        for finding in getattr(result, "findings", []) or []:
            hints.append({
                "engine": finding.engine,
                "rule_id": finding.rule_id,
                "cwe": int(finding.cwe),
                "severity": finding.severity,
                "confidence": float(finding.confidence),
                "file": finding.file,
                "line": int(finding.line),
                "end_line": finding.end_line,
                "message": finding.message,
                "taint_metadata": finding.taint_metadata or {},
            })
    return hints


def apply_engine_graph(project: str, build_id: int,
                       nodes: list[dict], edges: list[dict]) -> dict:
    """写入引擎图增量（calls/dataflow），幂等、去重、上限 20k 边。"""
    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.db.pool import get_conn
    from codesentry.rag.extractors.base import CodeEdge, CodeNode
    from codesentry.rag.graph_build import _upsert_edge, _upsert_node

    if not build_id:
        return {"nodes": 0, "edges": 0, "error": "no graph_build_id"}
    ensure_control_schema()
    node_count = 0
    edge_count = 0
    seen_edges: set[tuple[str, str, str]] = set()
    truncated = False
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT node_key FROM graph_nodes WHERE project=%s", (project,))
        existing = {r[0] for r in cur.fetchall()}

        def ensure_node(key: str) -> None:
            if not key or key in existing:
                return
            kind, path = _node_kind_path(key)
            _upsert_node(cur, project, build_id, CodeNode(
                key=key, kind=kind, name=key.rsplit("/", 1)[-1][:120],
                path=path, lang="", attrs={"placeholder": True},
            ))
            existing.add(key)

        for node in nodes[:5000]:
            key = str(node.get("key") or "")
            if not key:
                continue
            _upsert_node(cur, project, build_id, CodeNode(
                key=key, kind=str(node.get("kind") or "external"),
                name=str(node.get("name") or key)[:200],
                path=str(node.get("path") or ""),
                start_line=int(node.get("start") or 0),
                end_line=int(node.get("end") or 0),
                qualified_name=str(node.get("qualified_name") or ""),
                lang=str(node.get("lang") or ""),
                attrs=node.get("attrs") or {},
            ))
            node_count += 1
        for edge in edges:
            src = str(edge.get("src") or "")
            dst = str(edge.get("dst") or "")
            kind = str(edge.get("kind") or "dataflow")
            if not src or not dst or src == dst:
                continue
            dedup = (src, dst, kind)
            if dedup in seen_edges:
                continue
            if edge_count >= 20000:
                truncated = True
                break
            seen_edges.add(dedup)
            ensure_node(src)
            ensure_node(dst)
            _upsert_edge(cur, project, build_id, CodeEdge(
                src, dst, kind,
                provenance=str(edge.get("provenance") or "engine"),
                confidence=float(edge.get("confidence") or 0.7),
                attrs=edge.get("attrs") or {},
            ))
            edge_count += 1
        conn.commit()
    return {"nodes": node_count, "edges": edge_count,
            "calls": sum(1 for s, _d, k in seen_edges if k == "calls"),
            "dataflow": sum(1 for s, _d, k in seen_edges if k == "dataflow"),
            "truncated": truncated}


def _node_kind_path(key: str) -> tuple[str, str]:
    if key.startswith("file:"):
        return "file", key[len("file:"):]
    for prefix, kind in (("function:", "function"), ("method:", "method"),
                         ("sink:", "sink"), ("source:", "source"),
                         ("class:", "class"), ("external:", "external")):
        if key.startswith(prefix):
            body = key[len(prefix):]
            path = body.split("#", 1)[0]
            return kind, path
    return "external", ""


def resolve_node_key(project: str, path: str, line: int,
                     fallback_kind: str = "source",
                     name: str = "") -> str:
    """把 file:line 映射到函数节点；失败退 file 节点，再退 source/sink 节点。"""
    from codesentry.rag.graph_query import node_for_location

    key = node_for_location(project, path, int(line or 0))
    if key:
        return key
    return f"file:{path}" if path else f"{fallback_kind}:{name or path}:{line}"


def apply_engine_hints(repo: str, build_id: int, hints: list[dict]) -> dict:
    """把引擎 hint 作为 sink 节点与 contains 边写入当前图。"""
    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.db.pool import get_conn
    from codesentry.rag.graph_build import _upsert_edge, _upsert_node
    from codesentry.rag.graph_query import node_for_location

    if not hints or not build_id:
        return {"applied": 0, "anchored": 0}
    ensure_control_schema()
    project = str(Path(repo).resolve())
    applied = 0
    anchored = 0
    with get_conn() as conn, conn.cursor() as cur:
        for hint in hints[:1000]:
            path = str(hint.get("file") or "")
            line = int(hint.get("line") or 0)
            if not path or line < 1:
                continue
            function_key = node_for_location(project, path, line)
            key = f"sink:{path}#{hint.get('engine')}:{hint.get('rule_id')}@{line}"
            _upsert_node(cur, project, build_id, CodeNode(
                key=key, kind="sink", name=str(hint.get("rule_id") or "engine-hint")[:120],
                path=path, start_line=line, end_line=int(hint.get("end_line") or line),
                lang="", attrs={
                    "provenance": hint.get("engine"),
                    "rule_id": hint.get("rule_id"),
                    "cwe": hint.get("cwe"),
                    "severity": hint.get("severity"),
                    "message": hint.get("message"),
                    "taint_metadata": hint.get("taint_metadata") or {},
                },
            ))
            applied += 1
            if function_key:
                anchored += 1
                _upsert_edge(cur, project, build_id, CodeEdge(
                    function_key, key, "contains",
                    provenance=str(hint.get("engine") or "engine"), confidence=0.8,
                ))
        conn.commit()
    return {"applied": applied, "anchored": anchored, "unresolved": applied - anchored}
