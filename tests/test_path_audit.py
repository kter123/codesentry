import uuid
from types import SimpleNamespace

from codesentry.agents.path_audit import run_path_audit
from codesentry.agents.path_audit_nodes import route_after_collect, route_audit, run_audit_path
from codesentry.control.audit_paths import claim_paths, coverage, finish_path, list_paths
from codesentry.db.pool import get_conn
from codesentry.rag.graph_build import build_graph
from codesentry.rag.path_build import build_paths


def _repo(tmp_path):
    (tmp_path / "app.py").write_text(
        "from flask import Flask, request\n"
        "app = Flask(__name__)\n"
        "@app.route('/run')\n"
        "def run():\n"
        "    cmd = request.args.get('cmd')\n"
        "    return eval(cmd)\n",
        encoding="utf-8",
    )
    return tmp_path


def test_build_paths_and_queue(tmp_path):
    sid = 100000 + (uuid.uuid4().int % 1000)
    repo = _repo(tmp_path)
    built = build_graph(str(repo), project=str(repo.resolve()))
    result = build_paths(sid, str(repo.resolve()), built["build_id"],
                         [{"file": "app.py", "line": 6, "rule_id": "eval",
                           "cwe": 95, "severity": "high", "message": "eval"}])
    assert result["candidates"] >= 1
    paths = list_paths(sid)
    assert paths and paths[0]["entry_key"] and paths[0]["sink_key"]
    assert paths[0]["feasibility"] in ("proven", "likely", "weak")
    claimed = claim_paths(sid, 2)
    assert claimed
    finish_path(claimed[0]["id"], "clean", {"reason": "test"})
    assert coverage(sid)["by_status"].get("clean", 0) >= 1


def test_path_audit_parses_finding(monkeypatch, tmp_path):
    repo = _repo(tmp_path)
    built = build_graph(str(repo), project=str(repo.resolve()))
    build_paths(100002, str(repo.resolve()), built["build_id"], [])
    path = list_paths(100002)[0]
    monkeypatch.setattr(
        "codesentry.agents.tools.run_tool_loop",
        lambda *a, **k: (
            (
                '{"verdict":"finding","confidence":0.9,"cwe":95,"severity":"high",'
                '"reason":"eval on request arg","fix_advice":"remove eval",'
                '"evidence":[{"file":"app.py","line":6,"snippet":"eval(cmd)"}]}'
            ),
            [{"tool": "read_source"}],
        ),
    )
    state = {"repo_path": str(repo), "engine_hints": []}
    runtime = SimpleNamespace(enabled=True, llm=object(), system=lambda: "audit",
                              max_iterations=3)
    result = run_path_audit(state, path, runtime=runtime)
    assert result["verdict"] == "finding"
    assert result["cwe"] == 95


def test_route_audit_send_and_finalize(tmp_path):
    state = {"repo_path": str(tmp_path), "scan_id": 1, "audit_paths": []}
    assert route_audit(state) == "triage"
    state["audit_paths"] = [{"id": 1}]
    sends = route_audit(state)
    assert isinstance(sends, list) and sends
    assert route_after_collect({**state, "audit_round": 99}) == "triage"


def _seed_scan_with_path(sid, repo, tmp_path):
    built = build_graph(str(repo), project=str(repo.resolve()))
    build_paths(sid, str(repo.resolve()), built["build_id"], [])
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scans (id, repo_path, license_oss, license_declared_at)"
            " VALUES (%s,%s,true,now()) ON CONFLICT (id) DO NOTHING",
            (sid, str(repo)),
        )
        conn.commit()
    return list_paths(sid)[0]


def test_run_audit_path_persists_live_finding(monkeypatch, tmp_path):
    sid = 102000 + (uuid.uuid4().int % 1000)
    repo = _repo(tmp_path)
    path = _seed_scan_with_path(sid, repo, tmp_path)
    monkeypatch.setattr(
        "codesentry.agents.path_audit.run_path_audit",
        lambda *a, **k: {"verdict": "finding", "cwe": 22, "severity": "high",
                         "confidence": 0.9, "reason": "traversal",
                         "evidence": [{"file": "app.py", "line": 6}]},
    )
    try:
        result = run_audit_path({"repo_path": str(repo), "scan_id": sid,
                                 "path": path})
        assert result["path_results"][0]["status"] == "finding"
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT rule_id,cwe,verdict,path_id FROM findings WHERE scan_id=%s", (sid,))
            row = cur.fetchone()
        assert row and row[1] == 22 and row[2] == "candidate" and row[3] == path["id"]
    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM findings WHERE scan_id=%s", (sid,))
            cur.execute("DELETE FROM audit_paths WHERE scan_id=%s", (sid,))
            cur.execute("DELETE FROM scans WHERE id=%s", (sid,))
            conn.commit()


def test_run_audit_path_marks_timeout(monkeypatch, tmp_path):
    sid = 103000 + (uuid.uuid4().int % 1000)
    repo = _repo(tmp_path)
    path = _seed_scan_with_path(sid, repo, tmp_path)
    monkeypatch.setattr(
        "codesentry.agents.path_audit.run_path_audit",
        lambda *a, **k: {"verdict": "need_more", "confidence": 0.0,
                         "reason": "单路径审计超时，保留待复查"},
    )
    try:
        run_audit_path({"repo_path": str(repo), "scan_id": sid,
                        "path": path})
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT status FROM audit_paths WHERE id=%s", (path["id"],))
            assert cur.fetchone()[0] == "timeout"
    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM audit_paths WHERE scan_id=%s", (sid,))
            cur.execute("DELETE FROM scans WHERE id=%s", (sid,))
            conn.commit()
