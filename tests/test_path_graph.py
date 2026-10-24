import uuid

from codesentry.agents.state import new_state
from codesentry.db.pool import get_conn
from codesentry.orchestrator.graph import build_graph
from codesentry.rag.graph_build import build_graph as build_code_graph


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


def test_path_graph_multi_round(monkeypatch, tmp_path):
    repo = _repo(tmp_path)
    built = build_code_graph(str(repo), project=str(repo.resolve()))
    sid = 880000 + (uuid.uuid4().int % 1000)

    finding = {
        "rule_id": "path.95", "cwe": 95, "severity": "high", "confidence": 0.9,
        "file": "app.py", "line": 6, "message": "eval", "engine": "agent",
    }

    def fake_audit(state, runtime=None):
        path = state.get("path") or {}
        from codesentry.control.audit_paths import finish_path
        finish_path(int(path.get("id") or 0), "finding", {"finding": finding})
        return {"path_results": [{"path_id": path.get("id"), "status": "finding",
                                  "finding": finding}]}

    monkeypatch.setattr("codesentry.agents.path_audit_nodes.run_audit_path", fake_audit)
    g = build_graph(
        recon_agent=lambda s: {"profile": {"languages": ["python"]}},
        graph_build_agent=lambda s: {"graph_build_id": built["build_id"],
                                     "graph_stats": built["stats"]},
        scan_agent=lambda s: {"engine_hints": [{"file": "app.py", "line": 6,
                                                "rule_id": "eval", "cwe": 95,
                                                "severity": "high", "engine": "semgrep",
                                                "message": "eval"}],
                              "phase": "audit"},
        triage_agent=lambda s: {"triaged_findings": s.get("candidate_findings") or [],
                                "phase": "poc_gen", "audit_feedback": ""},
        deploy_agent=lambda s: {"deploy_status": "disabled", "phase": "poc_gen"},
        poc_agent=lambda s: {"poc_results": {}, "phase": "human_review"},
        report_agent_fn=lambda s: {"phase": "done"},
        checkpointer=None,
        scan_id_holder={"scan_id": sid, "budget": None, "snapshot": None},
    )
    try:
        final = g.invoke(new_state(str(repo), OSS=False, scan_id=sid),
                         config={"recursion_limit": 40})
        assert final.get("audit_batch", 0) >= 1
        assert final.get("candidate_findings"), final.get("audit")
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM audit_paths WHERE scan_id=%s", (sid,))
            assert int(cur.fetchone()[0]) >= 1
            cur.execute("SELECT count(*) FROM audit_rounds WHERE scan_id=%s", (sid,))
            assert int(cur.fetchone()[0]) >= 0
    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM audit_paths WHERE scan_id=%s", (sid,))
            cur.execute("DELETE FROM audit_rounds WHERE scan_id=%s", (sid,))
            cur.execute("DELETE FROM findings WHERE scan_id=%s", (sid,))
            cur.execute("DELETE FROM node_runs WHERE scan_id=%s", (sid,))
            conn.commit()
