"""项目与定时扫描 API（P1）。"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from codesentry.web.server import app


class ProjectPayload(BaseModel):
    name: str
    repo_path: str = ""
    git_url: str = ""
    oss: bool = False
    enabled: bool = True


class ProjectPatch(BaseModel):
    name: str | None = None
    repo_path: str | None = None
    git_url: str | None = None
    oss: bool | None = None
    enabled: bool | None = None


class SchedulePayload(BaseModel):
    project_id: int
    name: str = ""
    cron: str = "0 3 * * *"
    enabled: bool = True


class SchedulePatch(BaseModel):
    name: str | None = None
    cron: str | None = None
    enabled: bool | None = None


@app.get("/api/projects")
async def list_projects() -> dict:
    from codesentry.control.projects import list_projects as _list

    return {"projects": _list()}


@app.post("/api/projects")
async def create_project(payload: ProjectPayload) -> dict:
    from codesentry.control.projects import create_project as _create

    try:
        return _create(payload.name, repo_path=payload.repo_path,
                       git_url=payload.git_url, oss=payload.oss,
                       enabled=payload.enabled)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.put("/api/projects/{project_id}")
async def update_project(project_id: int, payload: ProjectPatch) -> dict:
    from codesentry.control.projects import update_project as _update

    try:
        out = _update(project_id, payload.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if out is None:
        raise HTTPException(404)
    return out


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: int) -> dict:
    from codesentry.control.projects import delete_project as _delete

    if not _delete(project_id):
        raise HTTPException(404)
    return {"ok": True}


@app.get("/api/schedules")
async def list_schedules() -> dict:
    from codesentry.control.projects import list_schedules as _list

    return {"schedules": _list()}


@app.post("/api/schedules")
async def create_schedule(payload: SchedulePayload) -> dict:
    from codesentry.control.projects import create_schedule as _create

    try:
        return _create(payload.project_id, name=payload.name, cron=payload.cron,
                       enabled=payload.enabled)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.put("/api/schedules/{schedule_id}")
async def update_schedule(schedule_id: int, payload: SchedulePatch) -> dict:
    from codesentry.control.projects import update_schedule as _update

    try:
        out = _update(schedule_id, payload.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if out is None:
        raise HTTPException(404)
    return out


@app.delete("/api/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int) -> dict:
    from codesentry.control.projects import delete_schedule as _delete

    if not _delete(schedule_id):
        raise HTTPException(404)
    return {"ok": True}


@app.post("/api/schedules/{schedule_id}/run")
async def run_schedule_now(schedule_id: int) -> dict:
    from codesentry.control.projects import list_schedules
    from codesentry.control.scheduler import run_schedule

    row = next((s for s in list_schedules() if int(s["id"]) == int(schedule_id)), None)
    if row is None:
        raise HTTPException(404)
    try:
        scan_id = await run_in_threadpool(run_schedule, {
            "id": row["id"], "repo_path": row.get("repo_path") or "",
            "git_url": row.get("git_url") or "", "oss": row.get("oss") or False,
        })
    except Exception as e:
        raise HTTPException(503, f"定时扫描启动失败：{str(e)[:200]}") from e
    return {"ok": True, "scan_id": scan_id}
