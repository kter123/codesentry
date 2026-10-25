"""扫描暂停/恢复/停止（带节点边界检查）。"""

from __future__ import annotations

import time


class ScanStopped(Exception):
    pass


def _upsert(scan_id: int, *, paused: bool | None = None,
            stop_requested: bool | None = None, reason: str = "") -> None:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO scan_controls (scan_id, paused, stop_requested, reason)"
                " VALUES (%s, COALESCE(%s, FALSE), COALESCE(%s, FALSE), %s)"
                " ON CONFLICT (scan_id) DO UPDATE SET"
                " paused=COALESCE(%s, scan_controls.paused),"
                " stop_requested=COALESCE(%s, scan_controls.stop_requested),"
                " reason=CASE WHEN %s <> '' THEN %s ELSE scan_controls.reason END,"
                " updated_at=now()",
                (int(scan_id), paused, stop_requested, reason,
                 paused, stop_requested, reason, reason),
            )
            conn.commit()
    except Exception:  # noqa: BLE001, S110
        pass


def reset(scan_id: int) -> None:
    _upsert(scan_id, paused=False, stop_requested=False, reason="")


def request_pause(scan_id: int, reason: str = "user paused") -> None:
    _upsert(scan_id, paused=True, reason=reason)


def request_resume(scan_id: int, reason: str = "user resumed") -> None:
    _upsert(scan_id, paused=False, reason=reason)


def request_stop(scan_id: int, reason: str = "user stopped") -> None:
    _upsert(scan_id, stop_requested=True, reason=reason)


def state(scan_id: int) -> dict:
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT paused, stop_requested, reason, updated_at FROM scan_controls"
                " WHERE scan_id=%s",
                (int(scan_id),),
            )
            row = cur.fetchone()
        if not row:
            return {"paused": False, "stop_requested": False, "reason": ""}
        return {"paused": bool(row[0]), "stop_requested": bool(row[1]),
                "reason": row[2] or "", "updated_at": str(row[3])}
    except Exception:  # noqa: BLE001
        return {"paused": False, "stop_requested": False, "reason": ""}


def wait_if_paused(scan_id: int, max_wait_s: int = 300) -> None:
    """在节点边界等待；stop 优先；超时自动 stop。"""
    if not scan_id:
        return
    if state(scan_id).get("stop_requested"):
        raise ScanStopped("scan stop requested")
    deadline = time.time() + max(1, int(max_wait_s))
    while True:
        current = state(scan_id)
        if current.get("stop_requested"):
            raise ScanStopped("scan stop requested")
        if not current.get("paused"):
            return
        if time.time() >= deadline:
            request_stop(scan_id, "pause timeout")
            raise ScanStopped("pause timeout")
        time.sleep(0.5)
