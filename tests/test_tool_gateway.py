import json
import uuid
from types import SimpleNamespace

from codesentry.control import tool_gateway
from codesentry.db.pool import get_conn


def _cleanup(sid):
    with get_conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM tool_runs WHERE scan_id=%s", (sid,))
        c.commit()


def test_tool_unknown_and_missing(tmp_path):
    try:
        tool_gateway.run_tool(1, "nope", str(tmp_path))
        raise AssertionError("should reject")
    except ValueError:
        pass
    assert tool_gateway.run_tool(1, "gitleaks", str(tmp_path))["status"] == "unavailable"


def test_network_tool_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(tool_gateway.shutil, "which", lambda name: "/bin/x")
    out = tool_gateway.run_tool(1, "osv", str(tmp_path), allow_network=False)
    assert out["status"] == "unavailable"


def test_tool_normalizes_output(tmp_path, monkeypatch):
    sid = 970300 + uuid.uuid4().int % 1000
    monkeypatch.setattr(tool_gateway.shutil, "which", lambda name: "/bin/x")
    monkeypatch.setattr(
        tool_gateway.subprocess, "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"findings": [{"rule": "x", "file": "a.py"}]}),
            stderr="",
        ),
    )
    try:
        out = tool_gateway.run_tool(sid, "gitleaks", str(tmp_path))
        assert out["status"] == "ok" and out["count"] == 1
        runs = tool_gateway.list_runs(sid)
        assert runs and runs[0]["tool"] == "gitleaks"
    finally:
        _cleanup(sid)
