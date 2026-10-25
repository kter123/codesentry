import uuid

from codesentry.agents import supervisor
from codesentry.control import scan_control
from codesentry.db.pool import get_conn
from codesentry.orchestrator import events


def _cleanup(sid):
    with get_conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM agent_events WHERE scan_id=%s", (sid,))
        cur.execute("DELETE FROM scan_controls WHERE scan_id=%s", (sid,))
        c.commit()


def test_event_seq_and_replay():
    sid = 970000 + uuid.uuid4().int % 1000
    try:
        events.publish_event(sid, "node.start", agent="audit", payload={"x": 1})
        events.publish_event(sid, "node.end", agent="audit", payload={"x": 2})
        rows = events.list_events(sid)
        assert [r["seq"] for r in rows] == [1, 2]
        assert rows[0]["event_type"] == "node.start"
        assert events.list_events(sid, after_seq=1)[0]["seq"] == 2
    finally:
        _cleanup(sid)


def test_scan_control_stop():
    sid = 970100 + uuid.uuid4().int % 1000
    try:
        scan_control.request_pause(sid)
        assert scan_control.state(sid)["paused"] is True
        scan_control.request_resume(sid)
        assert scan_control.state(sid)["paused"] is False
        scan_control.request_stop(sid)
        assert scan_control.state(sid)["stop_requested"] is True
        try:
            scan_control.wait_if_paused(sid, 1)
            raise AssertionError("should stop")
        except scan_control.ScanStopped:
            pass
    finally:
        _cleanup(sid)


def test_supervisor_decisions(monkeypatch):
    sid = 970200 + uuid.uuid4().int % 1000
    monkeypatch.setattr("codesentry.control.audit_paths.coverage",
                        lambda scan_id: {"pending": 3, "rounds": 0})
    out = supervisor.run_supervisor({"scan_id": sid, "budget": {}})
    assert out["supervisor"]["action"] == "audit_paths"
    _cleanup(sid)

    monkeypatch.setattr("codesentry.control.audit_paths.coverage",
                        lambda scan_id: {"pending": 0, "rounds": 0})
    out = supervisor.run_supervisor({"scan_id": sid, "budget": {},
                                     "supervisor": {"audit_repo_done": True}})
    assert out["supervisor"]["action"] == "triage"
    out = supervisor.run_supervisor({"scan_id": sid, "budget": {},
                                     "supervisor": {"audit_repo_done": True,
                                                    "triaged": True}})
    assert out["supervisor"]["action"] == "report"

    out = supervisor.run_supervisor({"scan_id": sid, "budget": {},
                                     "candidate_findings": [{"x": 1}],
                                     "supervisor": {"audit_repo_done": True}})
    assert out["supervisor"]["action"] == "triage"
    _cleanup(sid)

    out = supervisor.run_supervisor({"scan_id": sid, "budget": {"phase": "breach"}})
    assert out["supervisor"]["action"] == "report"
    _cleanup(sid)


def test_agent_tree_groups():
    sid = 970400 + uuid.uuid4().int % 1000
    try:
        from codesentry.orchestrator.telemetry import node_run

        with node_run(sid, "scan"):
            pass
        nodes = events.list_agent_nodes(sid)
        keys = {n["agent_key"] for n in nodes}
        assert f"scan:{sid}" in keys
        assert "group:engine" in keys
        assert any(k.startswith("scan:") and k != f"scan:{sid}" for k in keys)
        group = next(n for n in nodes if n["agent_key"] == "group:engine")
        assert group["parent_key"] == f"scan:{sid}"
    finally:
        with get_conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM agent_nodes WHERE scan_id=%s", (sid,))
            c.commit()
