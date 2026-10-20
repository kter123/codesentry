import time
import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from codesentry.control import auth
from codesentry.db.pool import get_conn
from codesentry.web.server import app


def _mk_user(role: str) -> tuple[str, str]:
    username = f"unit-{role}-{uuid.uuid4().hex[:8]}"
    password = "pw-123456"
    assert auth.create_user(username, password, role=role, actor="test")
    return username, password


def _cleanup(username: str) -> None:
    with get_conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM api_tokens WHERE user_id IN (SELECT id FROM users WHERE username=%s)", (username,))
        cur.execute("DELETE FROM users WHERE username=%s", (username,))
        c.commit()


def _cleanup_scan(scan_id: int) -> None:
    with get_conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM findings WHERE scan_id=%s", (scan_id,))
        cur.execute("DELETE FROM node_runs WHERE scan_id=%s", (scan_id,))
        cur.execute("DELETE FROM budget_ledger WHERE scan_id=%s", (scan_id,))
        cur.execute("DELETE FROM scans WHERE id=%s", (scan_id,))
        c.commit()


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setenv("CODESENTRY_AUTH_ENABLED", "true")
    monkeypatch.setenv("CODESENTRY_SECRET_KEY", "unit-auth-secret")
    return TestClient(app)


def test_password_hash_roundtrip():
    h = auth.hash_password("pw-123456")
    assert h.startswith("scrypt$")
    assert auth.verify_password("pw-123456", h)
    assert not auth.verify_password("wrong", h)


def test_auth_disabled_by_default(monkeypatch):
    monkeypatch.setenv("CODESENTRY_AUTH_ENABLED", "false")
    c = TestClient(app)
    assert c.get("/api/agents/triage").status_code == 200
    me = c.get("/api/auth/me").json()
    assert me["auth_enabled"] is False and me["role"] == "admin"


def test_unauthenticated_401(auth_on):
    assert auth_on.get("/api/llm-profiles").status_code == 401


def test_login_me_and_logout(auth_on):
    username, password = _mk_user("admin")
    try:
        r = auth_on.post("/api/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, r.text
        me = auth_on.get("/api/auth/me").json()
        assert me["user"]["username"] == username and me["user"]["role"] == "admin"
        assert auth_on.post("/api/auth/logout").status_code == 200
        assert auth_on.get("/api/auth/me").status_code == 401
    finally:
        _cleanup(username)


def test_login_accepts_form(auth_on):
    username, password = _mk_user("admin")
    try:
        r = auth_on.post("/api/auth/login", data={"username": username, "password": password})
        assert r.status_code == 200, r.text
    finally:
        _cleanup(username)


def test_viewer_read_scans_but_cannot_write_config(auth_on):
    username, password = _mk_user("viewer")
    try:
        assert auth_on.post("/api/auth/login", json={"username": username, "password": password}).status_code == 200
        assert auth_on.get("/api/scans").status_code == 200
        assert auth_on.put("/api/agents/triage", json={"timeout_s": 1}).status_code == 403
        assert auth_on.get("/api/users").status_code == 403
    finally:
        _cleanup(username)


def test_analyst_can_create_scan(auth_on):
    username, password = _mk_user("analyst")
    scan_id = None
    try:
        assert auth_on.post("/api/auth/login", json={"username": username, "password": password}).status_code == 200
        r = auth_on.post("/api/scans", data={"diff_text": "x"})
        assert r.status_code == 200, r.text
        scan_id = r.json()["scan_id"]
        deadline = time.time() + 20
        while time.time() < deadline:
            with get_conn() as c, c.cursor() as cur:
                cur.execute("SELECT status FROM scans WHERE id=%s", (scan_id,))
                row = cur.fetchone()
            if not row or row[0] in ("done", "failed"):
                break
            time.sleep(0.1)
    finally:
        if scan_id:
            _cleanup_scan(scan_id)
        _cleanup(username)


def test_api_token_scope(auth_on):
    username, _ = _mk_user("admin")
    token_id = None
    try:
        ro = auth.create_api_token(None, "ro", ["scan:read"], actor="test")
        assert ro and ro["token"].startswith("cs_")
        token_id = ro["id"]
        h = {"Authorization": f"Bearer {ro['token']}"}
        assert auth_on.get("/api/scans", headers=h).status_code == 200
        assert auth_on.post("/api/scans", data={"diff_text": "x"}, headers=h).status_code == 403
        assert auth_on.post("/api/scans/1/resume", json={"decisions": []}, headers=h).status_code == 403
        assert auth_on.delete("/api/scans/1", headers=h).status_code == 403
    finally:
        if token_id:
            auth.revoke_api_token(token_id)
        _cleanup(username)


def test_disabled_user_token_is_rejected(auth_on):
    username, _ = _mk_user("analyst")
    token_id = None
    try:
        user = auth.get_user(username)
        tok = auth.create_api_token(user["id"], "analyst-token", ["scan:read"], actor="test")
        token_id = tok["id"]
        h = {"Authorization": f"Bearer {tok['token']}"}
        assert auth_on.get("/api/scans", headers=h).status_code == 200
        assert auth.update_user(user["id"], {"enabled": False}, actor="test")
        assert auth_on.get("/api/scans", headers=h).status_code == 401
    finally:
        if token_id:
            auth.revoke_api_token(token_id)
        _cleanup(username)


def test_websocket_requires_auth(auth_on):
    with auth_on.websocket_connect("/ws/scans/1") as ws:
        with pytest.raises(WebSocketDisconnect) as ei:
            ws.receive_text()
        assert ei.value.code == 4401
