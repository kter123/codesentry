import uuid

from codesentry.control import agent_config
from codesentry.db.pool import get_conn


def _restore(name: str, before: dict) -> None:
    with get_conn() as c, c.cursor() as cur:
        cur.execute(
            "UPDATE agent_configs SET enabled=%s, model_role=%s, display_name=%s,"
            " capabilities=%s, timeout_s=%s, max_iterations=%s, llm_profile_id=%s WHERE name=%s",
            (before["enabled"], before["model_role"], before["display_name"],
             __import__("json").dumps(before["capabilities"]), before["timeout_s"],
             before["max_iterations"], before["llm_profile_id"], name),
        )
        c.commit()


def test_defaults_for_six_agents():
    for name in ("recon", "scan", "retrieval", "triage", "poc_gen", "report"):
        cfg = agent_config.get_agent_config(name)
        assert cfg["name"] == name
        assert "capabilities" in cfg
    assert agent_config.get_agent_config("scan")["capabilities"]["engines"]


def test_missing_row_falls_back():
    with get_conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM agent_configs WHERE name='triage'")
        c.commit()
    try:
        cfg = agent_config.get_agent_config("triage")
        assert cfg["display_name"] == "Triage"
        assert cfg["model_role"] == "deep"
    finally:
        agent_config.ensure_agent_configs()


def test_update_merges_capabilities_and_audits():
    agent_config.ensure_agent_configs()
    before = agent_config.get_agent_config("triage")
    try:
        after = agent_config.update_agent_config("triage", {"capabilities": {"network": True}},
                                                 actor="unit")
        assert after["capabilities"]["network"] is True
        assert after["capabilities"]["engines"] == []
        from codesentry.control.audit import list_audit

        rows = list_audit(target_type="agent_config", actor="unit")
        assert any(r["target_id"] == "triage" for r in rows)
    finally:
        _restore("triage", before)


def test_poc_capabilities_forced_off(monkeypatch):
    monkeypatch.setenv("CODESENTRY_POC_RUN", "off")
    caps = agent_config.effective_capabilities("poc_gen")
    assert caps["network"] is False and caps["shell"] is False and caps["poc_exec"] is False
    assert agent_config.capability_allows("poc_gen", "poc_exec") is False


def test_agent_stats():
    agent = f"unit-{uuid.uuid4().hex[:8]}"
    with get_conn() as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO scans (repo_path, license_oss, license_declared_at) VALUES ('/tmp', false, now()) RETURNING id"
        )
        sid = cur.fetchone()[0]
        for dur in (100, 300):
            cur.execute(
                "INSERT INTO node_runs (scan_id, node, started_at, duration_ms, tokens, status)"
                " VALUES (%s,%s,now(),%s,%s,'ok')",
                (sid, agent, dur, 10),
            )
        c.commit()
    try:
        stats = agent_config.agent_stats(agent, days=1)
        assert stats["calls"] == 2
        assert stats["ok_calls"] == 2
        assert stats["success_rate"] == 1.0
        assert stats["p50_ms"] == 200
        assert stats["tokens"] == 20
    finally:
        with get_conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM node_runs WHERE node=%s", (agent,))
            cur.execute("DELETE FROM scans WHERE id=%s", (sid,))
            c.commit()
