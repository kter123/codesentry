import os
import time
import uuid

from codesentry.control.retention import (
    cleanup_codeql_cache,
    cleanup_orphan_workdirs,
    purge_scans,
)
from codesentry.db.pool import get_conn


def test_purge_scans_removes_audit_rows(tmp_path, monkeypatch):
    work = tmp_path / "work"
    repo = work / f"job-{uuid.uuid4().hex[:6]}" / "src"
    repo.mkdir(parents=True)
    monkeypatch.setenv("CODESENTRY_WORK_DIR", str(work))
    sid = 987000 + (uuid.uuid4().int % 1000)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scans (id, repo_path, license_oss, license_declared_at, created_at)"
            " VALUES (%s,%s,true,now() - interval '10 days', now() - interval '10 days')",
            (sid, str(repo)),
        )
        cur.execute(
            "INSERT INTO audit_paths (scan_id, path_key, round, kind, entry_key, sink_key,"
            " nodes, edges, length, score, feasibility, status)"
            " VALUES (%s,%s,0,'entry_to_sink','e','s','[]'::jsonb,'[]'::jsonb,1,0.1,'weak','clean')",
            (sid, "d" * 64),
        )
        cur.execute(
            "INSERT INTO audit_rounds (scan_id, round, paths_total) VALUES (%s,0,1)", (sid,)
        )
        conn.commit()
    assert purge_scans(1) >= 1
    with get_conn() as conn, conn.cursor() as cur:
        for table in ("audit_paths", "audit_rounds"):
            cur.execute(f"SELECT count(*) FROM {table} WHERE scan_id=%s", (sid,))
            assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM scans WHERE id=%s", (sid,))
        assert cur.fetchone()[0] == 0
    assert not repo.exists()


def test_cleanup_codeql_cache_only_old(tmp_path, monkeypatch):
    work = tmp_path / "work"
    cache = work / "codeql-db"
    old = cache / "old"
    new = cache / "new"
    old.mkdir(parents=True)
    new.mkdir(parents=True)
    monkeypatch.setenv("CODESENTRY_WORK_DIR", str(work))
    past = time.time() - 10 * 86400
    os.utime(old, (past, past))
    assert cleanup_codeql_cache(7) == 1
    assert not old.exists() and new.exists()


def test_cleanup_orphan_workdirs_keeps_referenced(tmp_path, monkeypatch):
    work = tmp_path / "work"
    keep = work / "keep" / "src"
    drop = work / "drop"
    keep.mkdir(parents=True)
    drop.mkdir(parents=True)
    monkeypatch.setenv("CODESENTRY_WORK_DIR", str(work))
    sid = 988000 + (uuid.uuid4().int % 1000)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scans (id, repo_path, license_oss, license_declared_at)"
            " VALUES (%s,%s,true,now())",
            (sid, str(keep)),
        )
        conn.commit()
    past = time.time() - 10 * 86400
    os.utime(drop, (past, past))
    try:
        assert cleanup_orphan_workdirs(7) == 1
        assert keep.exists() and not drop.exists()
    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM scans WHERE id=%s", (sid,))
            conn.commit()


def test_purge_keeps_shared_repo_job(tmp_path, monkeypatch):
    work = tmp_path / "work"
    repo = work / f"shared-{uuid.uuid4().hex[:6]}" / "src"
    repo.mkdir(parents=True)
    monkeypatch.setenv("CODESENTRY_WORK_DIR", str(work))
    old = 989000 + (uuid.uuid4().int % 500)
    new = old + 1
    with get_conn() as conn, conn.cursor() as cur:
        for sid, age in ((old, "10 days"), (new, "0 days")):
            cur.execute(
                "INSERT INTO scans (id, repo_path, license_oss, license_declared_at, created_at)"
                f" VALUES (%s,%s,true,now() - interval '{age}', now() - interval '{age}')",
                (sid, str(repo)),
            )
        conn.commit()
    try:
        purge_scans(1)
        assert repo.exists(), "shared repo must survive while another scan references it"
    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM scans WHERE id IN (%s,%s)", (old, new))
            conn.commit()
