import hashlib
import uuid

from codesentry.control.audit_paths import claim_paths, coverage, finish_path
from codesentry.db.pool import get_conn


def _sid() -> int:
    return 970000 + (uuid.uuid4().int % 10000)


def _key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _insert(sid: int, n: int, *, kind: str, feasibility: str, edges: list | None = None,
            sink: str = "sink:app.py#eval:1", entry: str = "endpoint:/run") -> None:
    with get_conn() as conn, conn.cursor() as cur:
        for i in range(n):
            cur.execute(
                "INSERT INTO audit_paths (scan_id, path_key, round, kind, entry_key,"
                " source_key, sink_key, nodes, edges, length, score, feasibility, status)"
                " VALUES (%s,%s,0,%s,%s,'',%s,%s::jsonb,%s::jsonb,2,%s,%s,'pending')",
                (sid, _key(f"{sid}:{kind}:{i}"), kind, f"{entry}:{i}", sink,
                 '["endpoint:/run","sink:app.py#eval:1"]',
                 __import__("json").dumps(edges or []),
                 0.9 if feasibility == "proven" else 0.2, feasibility),
            )
        conn.commit()


def _cleanup(sid: int) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM audit_paths WHERE scan_id=%s", (sid,))
        cur.execute("DELETE FROM audit_rounds WHERE scan_id=%s", (sid,))
        cur.execute("DELETE FROM scans WHERE id=%s", (sid,))
        conn.commit()


def test_claim_prioritizes_proven_and_caps_entry_only():
    sid = _sid()
    try:
        _insert(sid, 20, kind="entry_to_sink", feasibility="proven")
        _insert(sid, 20, kind="entry_only", feasibility="weak")
        claimed = claim_paths(sid, 5, max_paths=5, entry_only_max=1)
        assert len(claimed) == 5
        assert all(p["kind"] == "entry_to_sink" for p in claimed)
    finally:
        _cleanup(sid)


def test_claim_entry_only_cap():
    sid = _sid()
    try:
        _insert(sid, 10, kind="entry_only", feasibility="weak")
        claimed = claim_paths(sid, 5, max_paths=20, entry_only_max=2)
        assert len(claimed) == 2
        assert all(p["kind"] == "entry_only" for p in claimed)
        again = claim_paths(sid, 5, max_paths=20, entry_only_max=2)
        assert again == []
    finally:
        _cleanup(sid)


def test_claim_respects_global_max_across_batches():
    sid = _sid()
    try:
        _insert(sid, 10, kind="entry_to_sink", feasibility="likely")
        first = claim_paths(sid, 3, max_paths=4, entry_only_max=0)
        assert len(first) == 3
        for p in first:
            finish_path(p["id"], "clean", {"reason": "test"})
        second = claim_paths(sid, 3, max_paths=4, entry_only_max=0)
        assert len(second) == 1
        third = claim_paths(sid, 3, max_paths=4, entry_only_max=0)
        assert third == []
    finally:
        _cleanup(sid)


def test_coverage_reports_dataflow_and_sinks_total(tmp_path):
    sid = _sid()
    repo = tmp_path / "repo"
    repo.mkdir()
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO scans (id, repo_path, license_oss, license_declared_at)"
                " VALUES (%s,%s,true,now())",
                (sid, str(repo)),
            )
            cur.execute(
                "INSERT INTO graph_nodes (project, node_key, kind, name, path, start_line,"
                " end_line, qualified_name, lang, attrs, build_id)"
                " VALUES (%s,'sink:app.py#eval:1','sink','eval','app.py',6,6,'','','{}'::jsonb,1)",
                (str(repo.resolve()),),
            )
            conn.commit()
        _insert(sid, 1, kind="entry_to_sink", feasibility="proven",
                edges=[{"from": "endpoint:/run", "to": "sink:app.py#eval:1",
                        "kind": "dataflow"}])
        cover = coverage(sid)
        assert cover["total"] >= 1
        assert cover["pending"] >= 1
        assert cover["dataflow_paths"] >= 1
        assert cover["sinks_total"] >= 1
        assert "entry_only" in cover and "batch" in cover and "max_rounds" in cover
    finally:
        _cleanup(sid)
