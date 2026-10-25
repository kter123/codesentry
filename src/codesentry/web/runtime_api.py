"""运行时 API：Agent 事件、SSE、Agent 树、暂停/恢复/停止。"""

from __future__ import annotations

import asyncio
import json

from fastapi.responses import StreamingResponse

from codesentry.web.server import app


@app.get("/api/scans/{scan_id}/events")
async def scan_events(scan_id: int, after_seq: int = 0, limit: int = 200) -> dict:
    from codesentry.orchestrator.events import list_events

    return {"scan_id": scan_id, "events": list_events(scan_id, after_seq, limit)}


@app.get("/api/scans/{scan_id}/events/stream")
async def scan_events_stream(scan_id: int, after_seq: int = 0) -> StreamingResponse:
    from codesentry.orchestrator.events import list_events

    async def gen():
        cursor = int(after_seq)
        idle = 0
        while True:
            events = await asyncio.to_thread(list_events, scan_id, cursor, 200)
            for event in events:
                cursor = max(cursor, int(event.get("seq") or 0))
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                idle = 0
            if not events:
                idle += 1
                await asyncio.sleep(1.0)
                if idle % 15 == 0:
                    yield ": keepalive\n\n"
            await asyncio.sleep(0.3)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/scans/{scan_id}/agent-tree")
async def agent_tree(scan_id: int) -> dict:
    from codesentry.db.pool import get_conn
    from codesentry.orchestrator.events import list_agent_nodes

    nodes = list_agent_nodes(scan_id)
    if not nodes:
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT node, status, started_at, ended_at, duration_ms, tokens,"
                    " tool_calls, error FROM node_runs WHERE scan_id=%s ORDER BY id",
                    (scan_id,),
                )
                rows = cur.fetchall()
            nodes = [{
                "agent_key": f"{r[0]}:{r[2]}", "parent_key": "root", "name": r[0],
                "phase": r[0], "status": r[1], "tokens": int(r[5] or 0),
                "tool_calls": int(r[6] or 0), "started_at": str(r[2]),
                "ended_at": str(r[3]) if r[3] else None,
                "summary": r[7] or f"{int(r[4] or 0)}ms",
            } for r in rows]
        except Exception:  # noqa: BLE001
            nodes = []
    return {"scan_id": scan_id, "root": "scan", "nodes": nodes}


@app.get("/api/scans/{scan_id}/control")
async def get_scan_control(scan_id: int) -> dict:
    from codesentry.control.scan_control import state

    return {"scan_id": scan_id, **state(scan_id)}


async def _control(scan_id: int, action: str) -> dict:
    from codesentry.control.scan_control import (
        request_pause,
        request_resume,
        request_stop,
        state,
    )
    from codesentry.orchestrator.events import publish_event

    if action == "pause":
        request_pause(scan_id)
    elif action == "resume":
        request_resume(scan_id)
    else:
        request_stop(scan_id)
    publish_event(scan_id, f"scan.{action}", agent="user", phase="control",
                  payload={"action": action})
    return {"scan_id": scan_id, "action": action, **state(scan_id)}


@app.post("/api/scans/{scan_id}/pause")
async def pause_scan(scan_id: int) -> dict:
    return await _control(scan_id, "pause")


@app.post("/api/scans/{scan_id}/resume")
async def resume_scan(scan_id: int) -> dict:
    return await _control(scan_id, "resume")


@app.post("/api/scans/{scan_id}/stop")
async def stop_scan(scan_id: int) -> dict:
    return await _control(scan_id, "stop")
