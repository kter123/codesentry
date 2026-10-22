

from codesentry.agents.confidence import calibrate, compute, evidence_score
from codesentry.agents.poc_gen import run_poc_gen
from codesentry.agents.state import new_state
from codesentry.control import calibration
from codesentry.db.pool import get_conn
from codesentry.orchestrator.artifacts import list_artifacts, verify_chain, write_artifact
from codesentry.orchestrator.graph import build_graph
from codesentry.sandbox.deploy import (
    DeployResult,
    detect_port,
    detect_recipe,
    resolve_project_root,
    run_deploy,
)
from codesentry.sandbox.verify import CanaryResult, CanaryVerifier


def test_detect_recipe(tmp_path):
    assert detect_recipe(str(tmp_path)) is None
    py = tmp_path / "py"; py.mkdir(); (py / "app.py").write_text("x=1")
    assert detect_recipe(str(py)) == "python"
    php = tmp_path / "php"; php.mkdir(); (php / "index.php").write_text("<?php")
    assert detect_recipe(str(php)) == "php"


def test_run_deploy_off_still_deploys_by_default(monkeypatch, tmp_path):
    (tmp_path / "app.py").write_text("x=1")
    monkeypatch.setenv("CODESENTRY_DEPLOY_ENABLED", "true")
    monkeypatch.setattr(
        "codesentry.sandbox.deploy.DockerDeployer.deploy",
        lambda self: DeployResult("ready", "ok", "http://127.0.0.1:1234/", "cid", "net"),
    )
    s = new_state(str(tmp_path), OSS=False, scan_id=1)
    u = run_deploy(s)
    assert u["deploy_status"] == "ready"


def test_run_deploy_can_be_disabled(monkeypatch, tmp_path):
    (tmp_path / "app.py").write_text("x=1")
    monkeypatch.setenv("CODESENTRY_DEPLOY_ENABLED", "false")
    s = new_state(str(tmp_path), OSS=False, scan_id=1)
    u = run_deploy(s)
    assert u["deploy_status"] == "disabled"


def test_resolve_project_root_and_port(tmp_path):
    nested = tmp_path / "pkg" / "web"
    nested.mkdir(parents=True)
    (nested / "Dockerfile").write_text("FROM nginx\nEXPOSE 9000\n")
    assert resolve_project_root(str(tmp_path)) == nested
    assert detect_port(nested, 8080) == 9000


def test_run_deploy_ready(monkeypatch, tmp_path):
    (tmp_path / "app.py").write_text("x=1")
    monkeypatch.setenv("CODESENTRY_DEPLOY_ENABLED", "true")
    monkeypatch.setattr(
        "codesentry.sandbox.deploy.DockerDeployer.deploy",
        lambda self: DeployResult("ready", "ok", "http://127.0.0.1:1234/", "cid", "net"),
    )
    s = new_state(str(tmp_path), OSS=False, scan_id=1)
    s["poc_run"] = "sandbox"
    u = run_deploy(s)
    assert u["deploy_status"] == "ready"
    assert u["target_url"].startswith("http://127.0.0.1")


def test_graph_deploy_between_triage_and_poc():
    order = []
    g = build_graph(
        recon_agent=lambda s: {"profile": {"languages": ["python"]}},
        scan_agent=lambda s: {"engine_findings": []},
        retrieval_agent=lambda s: {"evidence": {}},
        triage_agent=lambda s: (order.append("triage"), {"triaged_findings": [], "phase": "poc_gen"})[1],
        deploy_agent=lambda s: (order.append("deploy"), {"deploy_status": "built", "phase": "poc_gen"})[1],
        poc_agent=lambda s: (order.append("poc"), {"poc_results": {}, "phase": "report"})[1],
        report_agent_fn=lambda s: {"phase": "done"},
        checkpointer=None,
        scan_id_holder={"scan_id": 0, "budget": None},
    )
    g.invoke(new_state("/r", OSS=False), config={"recursion_limit": 20})
    assert order == ["triage", "deploy", "poc"]


def test_artifact_chain_detects_tamper():
    with get_conn() as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO scans (repo_path, license_oss, license_declared_at) VALUES ('/tmp/art',false,now()) RETURNING id"
        )
        sid = int(cur.fetchone()[0]); c.commit()
    try:
        d1 = write_artifact(scan_id=sid, seq=1, node="recon", input_obj={"a": 1}, output_obj={"b": 2})
        d2 = write_artifact(scan_id=sid, seq=2, node="scan", input_obj={"b": 2}, output_obj={"c": 3},
                            prev_sha256=d1 or "")
        assert d1 and d2
        assert verify_chain(sid)["ok"] is True
        assert len(list_artifacts(sid)) == 2
        with get_conn() as c, c.cursor() as cur:
            cur.execute("UPDATE agent_artifacts SET prev_sha256='deadbeef' WHERE scan_id=%s AND seq=2", (sid,))
            c.commit()
        assert verify_chain(sid)["ok"] is False
    finally:
        with get_conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM agent_artifacts WHERE scan_id=%s", (sid,))
            cur.execute("DELETE FROM scans WHERE id=%s", (sid,))
            c.commit()


def test_confidence_parts_and_gate():
    ev = evidence_score({"code": [{"path": "a"}], "kb": []}, has_chain=True)
    assert ev >= 0.7
    parts = compute(0.8, ev, calibrate(0.8, 1.0, 0.0), "keep")
    assert parts["final"] <= 0.8
    reject = compute(0.9, 0.9, 0.9, "reject")
    assert reject["verdict_gated"] == 0.1


def test_calibration_fit_and_ece():
    pairs = [{"raw": 0.9, "label": 1}, {"raw": 0.8, "label": 1}, {"raw": 0.2, "label": 0}]
    params = calibration.fit(pairs)
    assert 0.1 <= params["a"] <= 3.0
    assert params["ece"] <= 1.0
    assert calibration.ece(pairs, 1.0, 0.0) >= 0.0


def test_poc_canary_verified(monkeypatch, tmp_path):
    monkeypatch.setenv("CODESENTRY_POC_RUN", "sandbox")
    monkeypatch.setenv("CODESENTRY_WORK_DIR", str(tmp_path))
    monkeypatch.setattr(
        "codesentry.sandbox.verify.verify_poc",
        lambda *a, **k: CanaryResult(True, "canary", "nonce123", "hit"),
    )

    class L:
        def complete(self, *a, **k):
            return '{"exploit_chain": ["a"], "poc_script": "print(1)", "notes": ""}'

    s = new_state("/r", OSS=False, scan_id=1)
    s["deploy_status"] = "ready"
    s["target_url"] = "http://127.0.0.1:1234/"
    s["triaged_findings"] = [{"rule_id": "x", "cwe": 134, "line": 1, "file": "a.c", "confidence": 0.8}]
    u = run_poc_gen(s, llm=L())
    poc = u["poc_results"]["x@1"]
    assert poc["verdict"] == "verified"
    assert poc["verification_method"] == "canary"
    assert poc["verification_nonce"] == "nonce123"


def test_verify_echo_with_fake_container(monkeypatch):
    v = CanaryVerifier(1)
    monkeypatch.setattr(v, "_exec", lambda script: f"CODESENTRY-{script.split('CODESENTRY-')[-1]}")
    res = v.verify_echo("echo {CANARY_CMD}", "abc123")
    assert res.ok and res.method == "canary"


def test_verify_requires_canary_placeholder():
    res = CanaryVerifier(1).verify_poc("print(1)")
    assert res.ok is False
    assert "占位符" in res.log
