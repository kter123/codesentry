import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from codesentry.control.projects import (
    claim_due_schedules,
    create_project,
    create_schedule,
    cron_next,
    delete_project,
    parse_cron,
    validate_repo_path,
)
from codesentry.db.pool import get_conn
from codesentry.web.server import app

client = TestClient(app)


def test_cron_next_basic():
    base = datetime(2026, 10, 25, 10, 2, tzinfo=UTC)
    assert cron_next("*/5 * * * *", base) == datetime(2026, 10, 25, 10, 5, tzinfo=UTC)
    assert cron_next("0 3 * * *", base) == datetime(2026, 10, 26, 3, 0, tzinfo=UTC)
    assert cron_next("15 4 * * *", base) == datetime(2026, 10, 26, 4, 15, tzinfo=UTC)


def test_cron_parse_rejects_bad():
    with pytest.raises(ValueError):
        parse_cron("* * *")
    with pytest.raises(ValueError):
        parse_cron("61 * * * *")
    with pytest.raises(ValueError):
        cron_next("bad")


def test_project_path_must_be_under_work(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESENTRY_WORK_DIR", str(tmp_path / "work"))
    inside = tmp_path / "work" / "repo"
    inside.mkdir(parents=True)
    assert validate_repo_path(str(inside)) == str(inside.resolve())
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ValueError):
        validate_repo_path(str(outside))


def test_project_and_schedule_crud_and_claim(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESENTRY_WORK_DIR", str(tmp_path / "work"))
    repo = tmp_path / "work" / f"repo-{uuid.uuid4().hex[:6]}"
    repo.mkdir(parents=True)
    name = f"proj-{uuid.uuid4().hex[:6]}"
    project = create_project(name, repo_path=str(repo))
    schedule = create_schedule(project["id"], name="nightly", cron="0 3 * * *")
    try:
        assert schedule["project_id"] == project["id"]
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE scan_schedules SET next_run_at=%s WHERE id=%s",
                (datetime.now(UTC) - timedelta(minutes=1), schedule["id"]),
            )
            conn.commit()
        claimed = claim_due_schedules(datetime.now(UTC))
        assert any(int(s["id"]) == schedule["id"] for s in claimed)
        again = claim_due_schedules(datetime.now(UTC))
        assert all(int(s["id"]) != schedule["id"] for s in again)
    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM scan_schedules WHERE id=%s", (schedule["id"],))
            conn.commit()
        delete_project(project["id"])


def test_projects_api(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESENTRY_WORK_DIR", str(tmp_path / "work"))
    repo = tmp_path / "work" / f"api-{uuid.uuid4().hex[:6]}"
    repo.mkdir(parents=True)
    name = f"api-{uuid.uuid4().hex[:6]}"
    res = client.post("/api/projects", json={"name": name, "repo_path": str(repo)})
    assert res.status_code == 200, res.text
    pid = res.json()["id"]
    try:
        rows = client.get("/api/projects").json()["projects"]
        assert any(p["id"] == pid for p in rows)
        s = client.post("/api/schedules", json={"project_id": pid, "cron": "*/5 * * * *"})
        assert s.status_code == 200, s.text
        sid = s.json()["id"]
        assert any(x["id"] == sid for x in client.get("/api/schedules").json()["schedules"])
        assert client.delete(f"/api/schedules/{sid}").status_code == 200
    finally:
        client.delete(f"/api/projects/{pid}")
