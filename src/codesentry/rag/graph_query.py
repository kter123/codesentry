"""代码图查询（G3）：邻域、路径、入口、可达闭包与 finding 子图。"""

from __future__ import annotations

from collections import deque


def _project(repo_or_project: str) -> str:

    return repo_or_project or ""


def node(project: str, key: str) -> dict | None:
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT node_key, kind, name, path, qualified_name, start_line, end_line, lang, attrs"
            " FROM graph_nodes WHERE project=%s AND node_key=%s",
            (project, key),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "key": row[0], "kind": row[1], "name": row[2], "path": row[3],
        "qualified_name": row[4], "start": row[5], "end": row[6],
        "lang": row[7], "attrs": row[8] or {},
    }


def neighbors(project: str, key: str, depth: int = 1,
              edge_kinds: list[str] | None = None,
              direction: str = "both") -> dict:
    if not key:
        return {"nodes": [], "edges": []}
    depth = max(1, min(int(depth), 6))
    kinds = tuple(edge_kinds or [])
    seen = {key}
    queue = deque([(key, 0)])
    edges: list[dict] = []
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        while queue:
            current, dist = queue.popleft()
            if dist >= depth:
                continue
            params: tuple
            if direction == "out":
                clause, params = "src_key=%s", (project, current)
            elif direction == "in":
                clause, params = "dst_key=%s", (project, current)
            else:
                clause, params = "(src_key=%s OR dst_key=%s)", (project, current, current)
            sql = f"SELECT src_key, dst_key, kind, provenance, confidence FROM graph_edges WHERE project=%s AND {clause}"
            if kinds:
                sql += " AND kind = ANY(%s)"
                params = (*params, list(kinds))
            sql += " LIMIT 500"
            cur.execute(sql, params)
            for src, dst, kind, provenance, confidence in cur.fetchall():
                edges.append({"from": src, "to": dst, "kind": kind,
                              "provenance": provenance, "confidence": confidence})
                nxt = dst if src == current else src
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append((nxt, dist + 1))
        nodes = _nodes(cur, project, seen)
    return {"nodes": nodes, "edges": _dedupe_edges(edges)}


def paths(project: str, src: str, dst: str, max_depth: int = 6,
          edge_kinds: list[str] | None = None) -> list[dict]:
    if not src or not dst:
        return []
    max_depth = max(1, min(int(max_depth), 8))
    kinds = tuple(edge_kinds or [])
    from codesentry.db.pool import get_conn

    parent: dict[str, tuple[str, str]] = {}
    seen = {src}
    queue = deque([(src, 0)])
    with get_conn() as conn, conn.cursor() as cur:
        while queue:
            current, dist = queue.popleft()
            if dist >= max_depth:
                continue
            sql = ("SELECT src_key, dst_key, kind FROM graph_edges"
                   " WHERE project=%s AND src_key=%s")
            params: tuple = (project, current)
            if kinds:
                sql += " AND kind = ANY(%s)"
                params = (*params, list(kinds))
            sql += " LIMIT 500"
            cur.execute(sql, params)
            for s, d, kind in cur.fetchall():
                if d in seen:
                    continue
                seen.add(d)
                parent[d] = (s, kind)
                if d == dst:
                    return [_build_path(parent, src, dst)]
                queue.append((d, dist + 1))
    return []


def reachable(project: str, keys: list[str], depth: int = 4,
              direction: str = "both") -> set[str]:
    out: set[str] = set()
    for key in keys:
        result = neighbors(project, key, depth=depth, direction=direction)
        out.update(n["key"] for n in result["nodes"])
    return out


def entrypoints(project: str, permission: str | None = None) -> list[dict]:
    from codesentry.db.pool import get_conn

    sql = ("SELECT endpoint_key, method, route, permission, path, line, evidence, mismatch"
           " FROM graph_endpoints WHERE project=%s")
    params: tuple = (project,)
    if permission:
        sql += " AND permission=%s"
        params = (project, permission)
    sql += " ORDER BY route, method"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [
        {"key": r[0], "method": r[1], "route": r[2], "permission": r[3],
         "path": r[4], "line": r[5], "evidence": r[6], "mismatch": r[7]}
        for r in rows
    ]


def node_for_location(project: str, path: str, line: int) -> str | None:
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT node_key FROM graph_nodes WHERE project=%s AND path=%s"
            " AND start_line<=%s AND end_line>=%s AND kind IN ('function','method')"
            " ORDER BY (end_line-start_line) ASC LIMIT 1",
            (project, path, int(line), int(line)),
        )
        row = cur.fetchone()
    return row[0] if row else None


def subgraph_for_finding(project: str, finding: dict, depth: int = 2) -> dict:
    path = str(finding.get("file") or finding.get("path") or "")
    line = int(finding.get("line") or finding.get("start_line") or 0)
    key = node_for_location(project, path, line)
    if not key:
        return {"nodes": [], "edges": [], "anchor": None}
    sub = neighbors(project, key, depth=depth, edge_kinds=[
        "calls", "taints_to", "routes_to", "exposes", "contains",
    ])
    sub["anchor"] = key
    return sub


def graph_context(project: str, path: str, line: int, depth: int = 2) -> dict:
    """兼容旧调用：按位置取邻域。"""
    key = node_for_location(project, path, line)
    return neighbors(project, key, depth=depth) if key else {"nodes": [], "edges": []}


def _nodes(cur, project: str, keys: set[str]) -> list[dict]:
    if not keys:
        return []
    cur.execute(
        "SELECT node_key, kind, name, path, qualified_name, start_line, end_line, lang, attrs"
        " FROM graph_nodes WHERE project=%s AND node_key = ANY(%s)",
        (project, list(keys)),
    )
    return [
        {"key": r[0], "kind": r[1], "name": r[2], "path": r[3], "qualified_name": r[4],
         "start": r[5], "end": r[6], "lang": r[7], "attrs": r[8] or {}}
        for r in cur.fetchall()
    ]


def _dedupe_edges(edges: list[dict]) -> list[dict]:
    out, seen = [], set()
    for edge in edges:
        key = (edge["from"], edge["to"], edge["kind"])
        if key in seen:
            continue
        seen.add(key)
        out.append(edge)
    return out


def _build_path(parent: dict, src: str, dst: str) -> dict:
    nodes = [dst]
    edges = []
    current = dst
    while current != src:
        prev, kind = parent[current]
        edges.append({"from": prev, "to": current, "kind": kind})
        nodes.append(prev)
        current = prev
    nodes.reverse()
    edges.reverse()
    return {"nodes": nodes, "edges": edges}
