from types import SimpleNamespace

from codesentry.agents.audit import run_audit_agent
from codesentry.agents.deploy_agent import run_deploy_agent
from codesentry.agents.tools import build_tools
from codesentry.agents.triage import run_triage
from codesentry.models import EngineResult, Finding
from codesentry.rag.graph_delta import hints_from_engine_results


def _hint():
    return {
        "engine": "joern", "rule_id": "joern.cmd-injection", "cwe": 78,
        "severity": "high", "confidence": 0.7, "file": "app.py", "line": 4,
        "message": "exec sink", "taint_metadata": {},
    }


def test_engine_results_become_hints_not_findings():
    result = EngineResult(engine="joern", status="ok", findings=[
        Finding(rule_id="joern.cmd-injection", cwe=78, severity="high", confidence=0.7,
                file="app.py", line=4, message="exec", engine="joern"),
    ])
    hints = hints_from_engine_results([result])
    assert hints[0]["rule_id"] == "joern.cmd-injection"
    assert hints[0]["line"] == 4


def test_audit_falls_back_to_hints_without_llm(tmp_path):
    state = {"repo_path": str(tmp_path), "engine_hints": [_hint()]}
    update = run_audit_agent(state, runtime=None, llm=None)
    assert update["phase"] == "triage"
    assert update["candidate_findings"][0]["rule_id"] == "joern.cmd-injection"


def test_audit_parses_agent_findings(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "codesentry.agents.tools.run_tool_loop",
        lambda *a, **k: (
            (
                '{"findings": [{"rule_id": "agent.rce", "cwe": 78, '
                '"severity": "high", "file": "app.py", "line": 9, '
                '"confidence": 0.8, "message": "rce", "evidence": "graph path", '
                '"fix_advice": "fix"}]}'
            ),
            [{"tool": "graph_entrypoints"}],
        ),
    )
    state = {"repo_path": str(tmp_path), "engine_hints": []}
    runtime = SimpleNamespace(enabled=True, llm=object(), system=lambda: "audit",
                              max_iterations=3, tools_allow=[])
    update = run_audit_agent(state, runtime=runtime)
    assert update["candidate_findings"][0]["rule_id"] == "agent.rce"
    assert update["audit"]["tool_trace"]


def test_triage_consumes_candidate_findings(tmp_path):
    candidate = {
        "rule_id": "agent.rce", "cwe": 78, "severity": "high", "confidence": 0.8,
        "file": "app.py", "line": 9, "message": "rce", "engine": "agent",
    }
    update = run_triage({"repo_path": str(tmp_path), "candidate_findings": [candidate]})
    assert update["triaged_findings"][0]["rule_id"] == "agent.rce"


def test_deploy_agent_falls_back_without_llm(monkeypatch):
    called = {}

    def fake_deploy(state):
        called["ok"] = True
        return {"deploy_status": "disabled", "deploy_log": "fallback", "phase": "poc_gen"}

    monkeypatch.setattr("codesentry.sandbox.deploy.run_deploy", fake_deploy)
    monkeypatch.setattr(
        "codesentry.config.get_settings",
        lambda: SimpleNamespace(
            deploy_enabled=True, work_dir="/tmp/cs-deploy-test",
            deploy_timeout_s=30, deploy_mem_mb=128, deploy_cpu=0.5,
            deploy_network_mode="host",
        ),
    )
    update = run_deploy_agent({"scan_id": 1, "repo_path": "/tmp/nope"}, runtime=None, llm=None)
    assert called.get("ok") is True
    assert update["deploy_status"] == "disabled"


def test_rag_tools_are_available(tmp_path):
    tools = build_tools({"repo_path": str(tmp_path)})
    for name in ("graph_paths", "kb_search", "vuln_cases", "audit_patterns",
                 "scan_strategies", "engine_hints"):
        assert name in tools
