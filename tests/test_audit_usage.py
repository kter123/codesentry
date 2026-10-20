import uuid

from codesentry.control import audit, usage
from codesentry.db.pool import get_conn


def _cleanup_audit(target_id: str) -> None:
    with get_conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM config_audit WHERE target_id=%s", (target_id,))
        c.commit()


def _cleanup_usage(agent: str) -> None:
    with get_conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM llm_usage WHERE agent=%s", (agent,))
        c.commit()


def test_audit_write_redacts_and_lists():
    target = f"t-{uuid.uuid4().hex[:8]}"
    try:
        assert audit.audit_write(
            "tester", "update", "unit_test", target,
            {"api_key": "sk-secret", "name": "before"},
            {"name": "after", "nested": {"password": "p"}},
        )
        rows = audit.list_audit(target_type="unit_test", actor="tester")
        row = next(r for r in rows if r["target_id"] == target)
        assert row["before"]["api_key"] == "***"
        assert row["before"]["name"] == "before"
        assert row["after"]["nested"]["password"] == "***"
    finally:
        _cleanup_audit(target)


def test_record_and_summary():
    agent = f"unit-{uuid.uuid4().hex[:8]}"
    try:
        assert usage.record_usage(
            scan_id=None, agent=agent, profile_id=None, model="m",
            prompt_tokens=10, completion_tokens=5, cost_usd=0.25, latency_ms=100,
        )
        assert usage.record_usage(
            scan_id=None, agent=agent, profile_id=None, model="m",
            prompt_tokens=20, completion_tokens=10, cost_usd=0.5, latency_ms=300,
        )
        rows = usage.summary(group_by="agent")
        row = next(r for r in rows if r["key"] == agent)
        assert row["calls"] == 2
        assert row["prompt_tokens"] == 30
        assert row["completion_tokens"] == 15
        assert row["tokens"] == 45
        assert abs(row["cost_usd"] - 0.75) < 1e-6
        assert row["avg_latency_ms"] == 200
    finally:
        _cleanup_usage(agent)


def test_quota_status_and_set():
    old_tokens = usage._read_setting("llm_quota_tokens")
    old_usd = usage._read_setting("llm_quota_usd")
    try:
        assert usage.set_quota(tokens=1_000_000, usd=100.0)
        q = usage.quota_status()
        assert q["tokens_limit"] == 1_000_000
        assert q["usd_limit"] == 100.0
        assert 0 <= q["tokens_pct"] <= 1000
    finally:
        usage.set_quota(tokens=int(old_tokens or 0), usd=float(old_usd or 0.0))
