"""扫描事件总线：内存广播 + `agent_events` 持久化（可回放）。"""

from __future__ import annotations

import json
import threading
from collections import defaultdict

_lock = threading.Lock()
_pending: dict[int, list[dict]] = defaultdict(list)


def publish(scan_id: int, event: dict) -> None:
    if not scan_id:
        return
    with _lock:
        _pending[int(scan_id)].append(event)


def drain(scan_id: int) -> list[dict]:
    with _lock:
        return _pending.pop(int(scan_id), [])


def room_ids() -> list[int]:
    with _lock:
        return list(_pending.keys())


def publish_event(scan_id: int, event_type: str, *, agent: str = "",
                  phase: str = "", payload: dict | None = None) -> dict:
    """事件先落库（seq 连续），再广播；写库失败仍广播。"""
    event = {
        "event": event_type,
        "event_type": event_type,
        "agent": agent,
        "phase": phase,
        "payload": payload or {},
        "scan_id": int(scan_id),
    }
    seq = 0
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (int(scan_id),))
            cur.execute(
                "SELECT coalesce(max(seq),0)+1 FROM agent_events WHERE scan_id=%s",
                (int(scan_id),),
            )
            seq = int(cur.fetchone()[0])
            cur.execute(
                "INSERT INTO agent_events (scan_id, seq, event_type, agent, phase, payload)"
                " VALUES (%s,%s,%s,%s,%s,%s::jsonb)",
                (int(scan_id), seq, event_type, agent, phase,
                 json.dumps(payload or {}, ensure_ascii=False)[:8000]),
            )
            conn.commit()
    except Exception:  # noqa: BLE001
        seq = 0
    event["seq"] = seq
    publish(int(scan_id), event)
    return event


def list_events(scan_id: int, after_seq: int = 0, limit: int = 200) -> list[dict]:
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT seq, event_type, agent, phase, payload, created_at"
                " FROM agent_events WHERE scan_id=%s AND seq>%s"
                " ORDER BY seq LIMIT %s",
                (int(scan_id), int(after_seq), max(1, min(int(limit), 1000))),
            )
            rows = cur.fetchall()
        return [{"scan_id": scan_id, "seq": r[0], "event": r[1],
                 "event_type": r[1], "agent": r[2], "phase": r[3],
                 "payload": r[4] or {}, "created_at": str(r[5])}
                for r in rows]
    except Exception:  # noqa: BLE001
        return []


def upsert_agent_node(scan_id: int, agent_key: str, *, name: str = "",
                      phase: str = "", status: str = "running",
                      parent_key: str = "root", tokens: int = 0,
                      tool_calls: int = 0, summary: str = "") -> None:
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agent_nodes (scan_id, agent_key, parent_key, name, phase,"
                " status, tokens, tool_calls, started_at, summary)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now(),%s)"
                " ON CONFLICT (scan_id, agent_key) DO UPDATE SET"
                " status=EXCLUDED.status, tokens=EXCLUDED.tokens,"
                " tool_calls=EXCLUDED.tool_calls, summary=EXCLUDED.summary,"
                " ended_at=CASE WHEN EXCLUDED.status IN ('ok','failed','stopped','skipped')"
                " THEN now() ELSE agent_nodes.ended_at END",
                (int(scan_id), agent_key, parent_key, name or agent_key, phase,
                 status, int(tokens), int(tool_calls), summary[:1000]),
            )
            conn.commit()
    except Exception:  # noqa: BLE001, S110
        pass


def list_agent_nodes(scan_id: int) -> list[dict]:
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT agent_key, parent_key, name, phase, status, tokens, tool_calls,"
                " started_at, ended_at, summary FROM agent_nodes"
                " WHERE scan_id=%s ORDER BY id",
                (int(scan_id),),
            )
            rows = cur.fetchall()
        keys = ["agent_key", "parent_key", "name", "phase", "status", "tokens",
                "tool_calls", "started_at", "ended_at", "summary"]
        return [{**dict(zip(keys, r)), "started_at": str(r[7]) if r[7] else None,
                 "ended_at": str(r[8]) if r[8] else None} for r in rows]
    except Exception:  # noqa: BLE001
        return []
