"""审计路径队列：认领、写回、扩展、覆盖率。"""

from __future__ import annotations

import json


def claim_paths(scan_id: int, limit: int = 8, lease_s: int = 900, *,
                max_paths: int | None = None,
                entry_only_max: int | None = None,
                priority: str = "proven_first",
                max_attempts: int = 2) -> list[dict]:
    """认领待审路径。

    - max_paths/entry_only_max 统计的是已审计（status != pending）的数量，跨轮次生效；
    - proven/likely/weak 优先，entry-only 只在剩余名额内认领；
    - FOR UPDATE SKIP LOCKED 保证并发认领不重复。
    """
    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.db.pool import get_conn

    ensure_control_schema()
    requested = max(1, min(int(limit), 32))
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FILTER (WHERE status <> 'pending'),"
            " count(*) FILTER (WHERE kind='entry_only' AND status <> 'pending')"
            " FROM audit_paths WHERE scan_id=%s",
            (int(scan_id),),
        )
        audited, entry_audited = cur.fetchone()
        audited = int(audited or 0)
        entry_audited = int(entry_audited or 0)
        remaining = requested
        if max_paths is not None:
            remaining = min(remaining, max(0, int(max_paths) - audited))
        entry_remaining: int | None = None
        if entry_only_max is not None:
            entry_remaining = max(0, int(entry_only_max) - entry_audited)
        if remaining <= 0:
            return []
        order = (
            "score DESC, id ASC"
            if priority == "score"
            else "CASE feasibility WHEN 'proven' THEN 0 WHEN 'likely' THEN 1 ELSE 2 END,"
                 " score DESC, id ASC"
        )
        ids: list[int] = []
        cur.execute(
            f"SELECT id FROM audit_paths WHERE scan_id=%s AND status='pending'"
            f" AND attempts < %s AND kind <> 'entry_only' ORDER BY {order} LIMIT %s"
            " FOR UPDATE SKIP LOCKED",
            (int(scan_id), max(1, int(max_attempts)), remaining),
        )
        ids.extend(int(r[0]) for r in cur.fetchall())
        if len(ids) < remaining and entry_remaining != 0:
            entry_limit = remaining - len(ids)
            if entry_remaining is not None:
                entry_limit = min(entry_limit, entry_remaining)
            if entry_limit > 0:
                cur.execute(
                    f"SELECT id FROM audit_paths WHERE scan_id=%s AND status='pending'"
                    f" AND attempts < %s AND kind='entry_only' ORDER BY {order}"
                    " LIMIT %s FOR UPDATE SKIP LOCKED",
                    (int(scan_id), max(1, int(max_attempts)), entry_limit),
                )
                ids.extend(int(r[0]) for r in cur.fetchall())
        if not ids:
            return []
        cur.execute(
            "UPDATE audit_paths p SET status='auditing',"
            " leased_until=now() + make_interval(secs => %s), attempts=attempts+1"
            " WHERE p.id = ANY(%s)"
            " RETURNING p.id, p.path_key, p.entry_key, p.source_key, p.sink_key,"
            " p.nodes, p.edges, p.length, p.score, p.feasibility, p.round, p.kind",
            (max(60, int(lease_s)), ids),
        )
        rows = cur.fetchall()
        conn.commit()
    keys = ("id", "path_key", "entry_key", "source_key", "sink_key", "nodes",
            "edges", "length", "score", "feasibility", "round", "kind")
    out = [dict(zip(keys, r)) for r in rows]
    if priority != "score":
        out.sort(key=lambda p: (
            {"proven": 0, "likely": 1}.get(str(p.get("feasibility")), 2),
            -float(p.get("score") or 0),
        ))
    return out


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
        by_status = {str(k): int(v) for k, v in cur.fetchall()}
        cur.execute(
            "SELECT count(DISTINCT entry_key),"
            " count(DISTINCT CASE WHEN sink_key <> '' THEN sink_key END),"
            " count(*),"
            " count(*) FILTER (WHERE kind='entry_only'),"
            " count(*) FILTER (WHERE EXISTS ("
            "   SELECT 1 FROM jsonb_array_elements(edges) e"
            "   WHERE e->>'kind' IN ('dataflow','taints_to')))"
            " FROM audit_paths WHERE scan_id=%s",
            (int(scan_id),),
        )
        entries, sinks, total, entry_only, dataflow_paths = cur.fetchone()
        cur.execute("SELECT max(round) FROM audit_paths WHERE scan_id=%s", (int(scan_id),))
        path_round = int(cur.fetchone()[0] or 0)
        cur.execute(
            "SELECT max(round), max(batch), max(paths_total) FROM audit_rounds WHERE scan_id=%s",
            (int(scan_id),),
        )
        round_row = cur.fetchone()
        round_no = max(path_round, int((round_row or [0])[0] or 0))
        batch = int((round_row or [0, 0])[1] or 0)
        cur.execute(
            "SELECT repo_path FROM scans WHERE id=%s",
            (int(scan_id),),
        )
        row = cur.fetchone()
        project = ""
        if row and row[0]:
            from pathlib import Path

            project = str(Path(str(row[0])).resolve())
        sinks_total = 0
        if project:
            cur.execute(
                "SELECT count(*) FROM graph_nodes WHERE project=%s AND kind='sink'",
                (project,),
            )
            sinks_total = int(cur.fetchone()[0] or 0)
    try:
        from codesentry.config import get_settings

        max_rounds = int(get_settings().audit_max_rounds)
    except Exception:  # noqa: BLE001
        max_rounds = 0
    return {
        "by_status": by_status,
        "total": int(total or 0),
        "pending": int(by_status.get("pending", 0)),
        "auditing": int(by_status.get("auditing", 0)),
        "paths": int(total or 0),
        "entries_covered": int(entries or 0),
        "sinks_covered": int(sinks or 0),
        "sinks_total": sinks_total,
        "entry_only": int(entry_only or 0),
        "dataflow_paths": int(dataflow_paths or 0),
        "rounds": round_no,
        "batch": batch,
        "max_rounds": max_rounds,
    }


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
