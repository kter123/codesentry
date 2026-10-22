"""GraphRAG（M3.5）：由 code_chunks 构建调用图，BFS 提供证据邻居。"""

from __future__ import annotations

from collections import deque


def build_code_graph(project: str) -> int:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT path, symbol_name, symbol_kind, start_line, end_line, call_refs"
                " FROM code_chunks WHERE project=%s",
                (project,),
            )
            chunks = cur.fetchall()
            name_map: dict[str, str] = {}
            for path, name, kind, start, end, _refs in chunks:
                key = f"{path}:{name}"
                name_map.setdefault(str(name), key)
                cur.execute(
                    "INSERT INTO code_graph_nodes (project, node_key, kind, name, path, start_line, end_line)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (project, node_key) DO NOTHING",
                    (project, key, kind, name, path, start, end),
                )
            edges = 0
            for path, name, _kind, _start, _end, refs in chunks:
                src = f"{path}:{name}"
                for ref in refs or []:
                    callee = str(ref).split(".")[-1]
                    dst = name_map.get(callee)
                    if not dst or dst == src:
                        continue
                    cur.execute(
                        "INSERT INTO code_graph_edges (project, src_key, dst_key, kind)"
                        " VALUES (%s,%s,%s,'calls')",
                        (project, src, dst),
                    )
                    edges += 1
            conn.commit()
        return len(chunks) + edges
    except Exception:  # noqa: BLE001
        return 0


def ensure_graph(project: str) -> None:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM code_graph_nodes WHERE project=%s", (project,))
            if int(cur.fetchone()[0]) > 0:
                return
        build_code_graph(project)
    except Exception:  # noqa: BLE001, S110
        pass


def neighbors(project: str, node_key: str, depth: int = 2) -> dict:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        seen = {node_key}
        queue = deque([(node_key, 0)])
        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        with get_conn() as conn, conn.cursor() as cur:
            while queue:
                key, d = queue.popleft()
                if d >= depth:
                    continue
                cur.execute(
                    "SELECT src_key, dst_key FROM code_graph_edges"
                    " WHERE project=%s AND (src_key=%s OR dst_key=%s)",
                    (project, key, key),
                )
                for src, dst in cur.fetchall():
                    edges.append({"from": src, "to": dst})
                    nxt = dst if src == key else src
                    if nxt not in seen:
                        seen.add(nxt)
                        queue.append((nxt, d + 1))
            if seen:
                cur.execute(
                    "SELECT node_key, kind, name, path, start_line, end_line FROM code_graph_nodes"
                    " WHERE project=%s AND node_key = ANY(%s)",
                    (project, list(seen)),
                )
                for r in cur.fetchall():
                    nodes[r[0]] = {"key": r[0], "kind": r[1], "name": r[2], "path": r[3],
                                   "start": r[4], "end": r[5]}
        return {"nodes": list(nodes.values()), "edges": edges}
    except Exception:  # noqa: BLE001
        return {"nodes": [], "edges": []}


def node_for_location(project: str, path: str, line: int) -> str | None:
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT node_key FROM code_graph_nodes"
                " WHERE project=%s AND path=%s AND start_line<=%s AND end_line>=%s"
                " ORDER BY (end_line-start_line) LIMIT 1",
                (project, path, int(line), int(line)),
            )
            row = cur.fetchone()
        return row[0] if row else None
    except Exception:  # noqa: BLE001
        return None


def graph_context(project: str, path: str, line: int, depth: int = 2) -> dict:
    key = node_for_location(project, path, line)
    return neighbors(project, key, depth) if key else {"nodes": [], "edges": []}
