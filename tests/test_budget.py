import os

import pytest

from codesentry.orchestrator.budget import BudgetGuard, BudgetPhase


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    os.environ.setdefault("CODESENTRY_DATABASE_URL", "postgresql://codesentry:devtest@127.0.0.1:5432/codesentry")
    for k in ("CODESENTRY_MAX_TOKENS", "CODESENTRY_MAX_TOOL_CALLS", "CODESENTRY_MAX_COST_USD", "CODESENTRY_MAX_FINDINGS"):
        monkeypatch.delenv(k, raising=False)
    yield
    from codesentry.db.pool import close_pool

    close_pool()


def test_phase_thresholds():
    g = BudgetGuard(scan_id=0)  # 不连库路径；record 迭代不落库时吞异常
    g.record(tokens=960_000)  # 80%
    assert g.phase_now() is BudgetPhase.WARN
    g.record(tokens=240_000)  # >100%
    assert g.phase_now() is BudgetPhase.BREACH
    assert g.breached()


def test_tool_call_and_cost():
    g = BudgetGuard(scan_id=1)
    g.record(tool_calls=1_350)  # 90%
    assert g.phase_now() is BudgetPhase.WARN
    g2 = BudgetGuard(scan_id=1)
    g2.record(cost_usd=30.0)
    assert g2.phase_now() is BudgetPhase.BREACH


def test_env_override(monkeypatch):
    monkeypatch.setenv("CODESENTRY_MAX_TOKENS", "100")
    BudgetGuard(scan_id=1)


def test_ledger_written(_clean_meta):
    import subprocess

    if subprocess.run(["docker", "ps", "--filter", "name=codesentry-db", "--filter", "status=running"], capture_output=True, check=False).returncode != 0:
        pytest.skip("db not running")
    from codesentry.db.ddl import render_full_ddl
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(render_full_ddl())
        cur.execute(
            "INSERT INTO scans (repo_path, license_oss, license_declared_at) VALUES ('/tmp/t', FALSE, now()) RETURNING id"
        )
        row = cur.fetchone()
        assert row is not None
        sid = row[0]
        cur.execute("DELETE FROM budget_ledger WHERE scan_id = %s", (sid,))
        conn.commit()
    g = BudgetGuard(scan_id=sid)
    g.record(tokens=10, tool_calls=2, cost_usd=0.5, phase="triage")
    with get_conn() as conn:
        cur = conn.execute("SELECT count(*) FROM budget_ledger WHERE scan_id = %s", (sid,))
        assert cur.fetchone()[0] >= 1


@pytest.fixture()
def _clean_meta():
    yield
