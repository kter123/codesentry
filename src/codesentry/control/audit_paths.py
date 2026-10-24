"""审计路径队列：认领、写回、扩展、覆盖率。"""

from __future__ import annotations

import json


def claim_paths(scan_id: int, limit: int = 8, lease_s: int = 900) -> list[dict]:
    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.db.pool import get_conn

    ensure_control_schema()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "WITH picked AS ("
            " SELECT id FROM audit_paths WHERE scan_id=%s AND status='pending'"
            " ORDER BY score DESC, id ASC LIMIT %s FOR UPDATE SKIP LOCKED"
            ") UPDATE audit_paths p SET status='auditing',"
            " leased_until=now() + make_interval(secs => %s), attempts=attempts+1"
            " FROM picked WHERE p.id=picked.id"
            " RETURNING p.id, p.path_key, p.entry_key, p.source_key, p.sink_key,"
            " p.nodes, p.edges, p.length, p.score, p.feasibility, p.round, p.kind",
            (int(scan_id), max(1, min(int(limit), 32)), max(60, int(lease_s))),
        )
        rows = cur.fetchall()
        conn.commit()
    keys = ("id", "path_key", "entry_key", "source_key", "sink_key", "nodes",
            "edges", "length", "score", "feasibility", "round", "kind")
    return [dict(zip(keys, r)) for r in rows]


def finish_path(path_id: int, status: str, result: dict | None = None) -> None:
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE audit_paths SET status=%s, evidence=%s::jsonb,"
            " finding_id=%s, leased_until=NULL, updated_at=now() WHERE id=%s",
            (status, json.dumps(result or {}), (result or {}).get("finding_id"),
             int(path_id)),
        )
        conn.commit()


def reclaim_expired(scan_id: int, lease_s: int = 900) -> int:
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE audit_paths SET status='pending', leased_until=NULL,"
            " updated_at=now() WHERE scan_id=%s AND status='auditing'"
            " AND (leased_until IS NULL OR leased_until < now())"
            " AND attempts < 3",
            (int(scan_id),),
        )
        n = cur.rowcount
        cur.execute(
            "UPDATE audit_paths SET status='error', leased_until=NULL, updated_at=now()"
            " WHERE scan_id=%s AND status='auditing'"
            " AND (leased_until IS NULL OR leased_until < now()) AND attempts >= 3",
            (int(scan_id),),
        )
        conn.commit()
    return int(n)


def list_paths(scan_id: int, status: str | None = None,
               round_no: int | None = None, limit: int = 100) -> list[dict]:
    from codesentry.db.pool import get_conn

    sql = ("SELECT id, path_key, round, kind, entry_key, source_key, sink_key,"
           " nodes, edges, length, score, feasibility, status, finding_id, evidence"
           " FROM audit_paths WHERE scan_id=%s")
    params: list = [int(scan_id)]
    if status:
        sql += " AND status=%s"
        params.append(status)
    if round_no is not None:
        sql += " AND round=%s"
        params.append(int(round_no))
    sql += " ORDER BY score DESC, id ASC LIMIT %s"
    params.append(max(1, min(int(limit), 500)))
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    keys = ["id", "path_key", "round", "kind", "entry_key", "source_key", "sink_key",
            "nodes", "edges", "length", "score", "feasibility", "status",
            "finding_id", "evidence"]
    return [dict(zip(keys, r)) for r in rows]


def coverage(scan_id: int) -> dict:
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status, count(*) FROM audit_paths WHERE scan_id=%s GROUP BY status",
            (int(scan_id),),
        )
        by_status = dict(cur.fetchall())
        cur.execute("SELECT count(DISTINCT entry_key), count(DISTINCT sink_key)"
                    " FROM audit_paths WHERE scan_id=%s", (int(scan_id),))
        entries, sinks = cur.fetchone()
        cur.execute("SELECT max(round) FROM audit_paths WHERE scan_id=%s", (int(scan_id),))
        max_round = cur.fetchone()[0] or 0
    return {"by_status": by_status, "entries_covered": int(entries or 0),
            "sinks_covered": int(sinks or 0), "rounds": int(max_round)}


def enqueue_paths(scan_id: int, paths: list[dict], round_no: int = 1) -> int:
    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.db.pool import get_conn

    ensure_control_schema()
    inserted = 0
    with get_conn() as conn, conn.cursor() as cur:
        for path in paths:
            cur.execute(
                "INSERT INTO audit_paths (scan_id, path_key, round, kind, entry_key,"
                " source_key, sink_key, nodes, edges, length, score, feasibility, status)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,'pending')"
                " ON CONFLICT (scan_id, path_key) DO NOTHING",
                (int(scan_id), path["path_key"], int(round_no), path.get("kind", "sibling"),
                 path.get("entry_key", ""), path.get("source_key", ""),
                 path.get("sink_key", ""), json.dumps(path.get("nodes") or []),
                 json.dumps(path.get("edges") or []), int(path.get("length") or 0),
                 float(path.get("score") or 0), path.get("feasibility", "likely")),
            )
            inserted += cur.rowcount
        conn.commit()
    return inserted


def sibling_paths(project: str, path: dict, max_siblings: int = 2) -> list[dict]:
    """同函数内的兄弟 sink：从同入口到其他 sink 的新路径。"""
    from codesentry.db.pool import get_conn

    nodes = path.get("nodes") or []
    sink = path.get("sink_key") or ""
    entry = path.get("entry_key") or ""
    if not nodes or not sink or not entry:
        return []
    function_key = ""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT src_key FROM graph_edges WHERE project=%s AND dst_key=%s AND kind='contains'",
            (project, sink),
        )
        row = cur.fetchone()
        if row:
            function_key = row[0]
        if not function_key:
            return []
        cur.execute(
            "SELECT dst_key FROM graph_edges WHERE project=%s AND src_key=%s AND kind='contains'",
            (project, function_key),
        )
        siblings = [r[0] for r in cur.fetchall()
                    if r[0] != sink and r[0].startswith("sink:")]
    out = []
    for sibling in siblings[:max_siblings]:
        key = _key(entry, sibling, nodes + [sibling])
        out.append({
            "path_key": key, "kind": "sibling",
            "entry_key": entry, "source_key": path.get("source_key", ""),
            "sink_key": sibling, "nodes": [*nodes, sibling],
            "edges": [*(path.get("edges") or [])], "length": len(nodes) + 1,
            "score": float(path.get("score") or 0) * 0.8,
            "feasibility": path.get("feasibility", "likely"),
        })
    return out


def _key(entry: str, sink: str, nodes: list[str]) -> str:
    import hashlib

    return hashlib.sha256(
        "|".join([entry, "", sink, ",".join(nodes)]).encode()
    ).hexdigest()
