import os
import subprocess

import pytest

from codesentry.orchestrator.telemetry import node_run

_DB_UP = (
    subprocess.run(
        ["docker", "ps", "--filter", "name=codesentry-db", "--filter", "status=running"],
        capture_output=True, check=False,
    ).returncode
    == 0
)

pytestmark = pytest.mark.skipif(not _DB_UP, reason="codesentry-db not running")


@pytest.fixture()
def _db(_fake_scan):
    os.environ.setdefault("CODESENTRY_DATABASE_URL", "postgresql://codesentry:devtest@127.0.0.1:5432/codesentry")
    from codesentry.db.ddl import render_full_ddl
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(render_full_ddl())
        conn.commit()
    yield
    from codesentry.db.pool import close_pool

    close_pool()


@pytest.fixture()
def _fake_scan():
    os.environ.setdefault("CODESENTRY_DATABASE_URL", "postgresql://codesentry:devtest@127.0.0.1:5432/codesentry")
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scans (repo_path, license_oss, license_declared_at) VALUES ('/tmp/tel', TRUE, now()) RETURNING id"
        )
        sid = cur.fetchone()[0]
        conn.commit()
    yield sid
    from codesentry.db.pool import get_conn as g2

    with g2() as conn:
        conn.execute("DELETE FROM node_runs WHERE scan_id = %s", (sid,))
        conn.execute("DELETE FROM scans WHERE id = %s", (sid,))
        conn.commit()


def test_node_run_ok_row_written(_db, _fake_scan):
    import time

    with node_run(_fake_scan, "recon", tokens=10, tool_calls=2):
        time.sleep(0.01)
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT status, error, duration_ms > 0 FROM node_runs WHERE scan_id = %s AND node = 'recon'", (_fake_scan,))
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "ok" and row[1] == "" and row[2] is True


def test_node_run_error_recorded_and_reraised(_db, _fake_scan):
    with pytest.raises(RuntimeError), node_run(_fake_scan, "triage"):
        raise RuntimeError("boom-triage")
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT status, error FROM node_runs WHERE scan_id = %s AND node = 'triage'", (_fake_scan,))
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "failed" and "boom-triage" in row[1]
