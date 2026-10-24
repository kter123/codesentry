"""OpenCode Go 真实 Agent 多轮测试（显式 -m live 运行，不进入默认 CI）。"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

import pytest

from codesentry.agents.audit import run_audit_agent
from codesentry.agents.deploy_agent import run_deploy_agent
from codesentry.agents.runtime import prepare_agent
from codesentry.agents.state import new_state
from codesentry.agents.triage import run_triage
from codesentry.rag.graph_build import build_graph

pytestmark = pytest.mark.live


def _require_opencode() -> None:
    from codesentry.agents.llm import LLMClient

    try:
        client = LLMClient.for_agent("audit")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"LLM 不可用：{exc}")
    if "opencode.ai" not in (client.base_url or ""):
        pytest.skip("当前默认 Profile 不是 OpenCode Go")


def _write(repo: Path, rel: str, body: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _vuln_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    _write(repo, "app.py", """
from flask import Flask, request
app = Flask(__name__)

@app.route("/run")
def run():
    cmd = request.args.get("cmd")
    return str(eval(cmd))

@app.route("/safe")
def safe():
    return "ok"
""".strip())
    return repo


def _hint() -> dict:
    return {
        "engine": "semgrep", "rule_id": "python.lang.security.eval", "cwe": 95,
        "severity": "high", "confidence": 0.7, "file": "app.py", "line": 7,
        "message": "eval on request parameter", "taint_metadata": {},
    }


def test_live_round1_audit_agent(tmp_path):
    _require_opencode()
    repo = _vuln_repo(tmp_path)
    built = build_graph(str(repo), project=str(repo.resolve()))
    state = new_state(str(repo), OSS=False)
    state["graph_build_id"] = built["build_id"]
    state["graph_stats"] = built["stats"]
    state["engine_hints"] = [_hint()]
    runtime = prepare_agent("audit", scan_id=0, with_llm=True)
    update = run_audit_agent(state, runtime=runtime)
    print("AUDIT", json.dumps(update.get("audit"), ensure_ascii=False)[:800])
    print("CANDIDATES", json.dumps(update.get("candidate_findings"), ensure_ascii=False)[:1200])
    assert update["phase"] == "triage"
    assert update["candidate_findings"], "AuditAgent 应至少保留 hint 候选"
    assert update["audit"].get("tool_trace") is not None


def test_live_round2_triage_agent(tmp_path):
    _require_opencode()
    repo = _vuln_repo(tmp_path)
    built = build_graph(str(repo), project=str(repo.resolve()))
    state = new_state(str(repo), OSS=False)
    state["graph_build_id"] = built["build_id"]
    state["graph_stats"] = built["stats"]
    state["candidate_findings"] = [{
        "rule_id": "agent.eval", "cwe": 95, "severity": "high", "confidence": 0.8,
        "file": "app.py", "line": 7, "message": "eval on request arg",
        "engine": "agent", "taint_metadata": {},
    }]
    runtime = prepare_agent("triage", scan_id=0, with_llm=True)
    update = run_triage(state, runtime=runtime)
    print("TRIAGED", json.dumps(update.get("triaged_findings"), ensure_ascii=False)[:1200])
    assert isinstance(update.get("triaged_findings"), list)


def test_live_round3_deploy_agent(tmp_path):
    _require_opencode()
    repo = tmp_path / "svc"
    _write(repo, "index.html", "<html><body>codesentry ok</body></html>")
    _write(repo, "Dockerfile", """
FROM nginx:latest
COPY index.html /usr/share/nginx/html/index.html
EXPOSE 80
""".strip())
    state = new_state(str(repo), OSS=False, scan_id=990001)
    runtime = prepare_agent("deploy", scan_id=990001, with_llm=True)
    update = run_deploy_agent(state, runtime=runtime)
    print("DEPLOY", json.dumps(update.get("deploy"), ensure_ascii=False)[:1500])
    print("LOG", update.get("deploy_log", "")[:800])
    print("STATUS", update.get("deploy_status"), update.get("target_url"))
    try:
        subprocess.run(
            ["docker", "rm", "-f", "codesentry-target-990001"],
            capture_output=True, check=False,
        )
    finally:
        assert update.get("deploy_status") in ("ready", "degraded", "disabled")


def test_live_round4_path_audit(tmp_path):
    _require_opencode()
    from codesentry.agents.path_audit import run_path_audit
    from codesentry.control.audit_paths import claim_paths
    from codesentry.rag.path_build import build_paths

    repo = _vuln_repo(tmp_path)
    built = build_graph(str(repo), project=str(repo.resolve()))
    sid = 990100 + (uuid.uuid4().int % 1000)
    build_paths(sid, str(repo.resolve()), built["build_id"], [_hint()])
    paths = claim_paths(sid, 1)
    assert paths, "应构建出至少一条 entry→sink 路径"
    state = new_state(str(repo), OSS=False, scan_id=sid)
    state["graph_build_id"] = built["build_id"]
    state["graph_stats"] = built["stats"]
    state["engine_hints"] = [_hint()]
    runtime = prepare_agent("audit", scan_id=sid, with_llm=True)
    result = run_path_audit(state, paths[0], runtime=runtime)
    print("PATH", json.dumps({k: result.get(k) for k in
                              ("verdict", "confidence", "cwe", "reason")},
                             ensure_ascii=False)[:800])
    assert result.get("verdict") in ("finding", "clean", "blocked", "need_more")
    assert result.get("tool_trace") is not None
    from codesentry.db.pool import get_conn
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM audit_paths WHERE scan_id=%s", (sid,))
        conn.commit()
