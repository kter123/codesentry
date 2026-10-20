from types import SimpleNamespace

from codesentry.agents import runtime as rt
from codesentry.agents.poc_gen import run_poc_gen
from codesentry.agents.state import new_state
from codesentry.agents.triage import run_triage
from codesentry.orchestrator.graph import build_graph
from codesentry.orchestrator.runner import _snapshot_agents


def _rt(agent="triage", *, enabled=True, llm=None, caps=None):
    return rt.AgentRuntime(
        agent=agent, enabled=enabled, llm=llm, system_prompt="SYS", prompt_version=2,
        prompt_fallback=False, skills_block="\n### Skill: s\nBODY", warnings=[],
        skills=[SimpleNamespace(name="taint", version=1, body_sha256="x" * 64)],
        capabilities=caps or {"poc_exec": True}, model_role="deep", profile_id=3,
    )


def test_graph_injects_runtime_only_when_declared(monkeypatch):
    monkeypatch.setattr(rt, "prepare_agent", lambda name, scan_id=0, **kw: _rt(name))
    seen = {}

    def triage(state, runtime=None, llm=None):
        seen["runtime"] = runtime
        return {"triaged_findings": [], "phase": "poc_gen"}

    g = build_graph(
        scan_agent=lambda s: {"engine_findings": [], "phase": "retrieval"},
        retrieval_agent=lambda s: {"evidence": {}, "phase": "triage"},
        triage_agent=triage,
        poc_agent=lambda s: {"poc_results": {}, "phase": "report"},
        report_agent_fn=lambda s: {"phase": "done"},
        checkpointer=None,
        scan_id_holder={"scan_id": 1, "budget": None},
    )
    g.invoke(new_state("/r", OSS=False), config={"recursion_limit": 10})
    assert seen["runtime"] is not None


def test_triage_uses_runtime_system():
    class L:
        def __init__(self):
            self.system = None

        def complete(self, system, user, model_role="deep"):
            self.system = system
            return '{"verdict":"keep","confidence":0.9,"rationale":"ok","fix_advice":""}'

    llm = L()
    s = new_state("/r", OSS=False)
    s["engine_findings"] = [{"rule_id": "x", "line": 1, "cwe": 918, "confidence": 0.5}]
    u = run_triage(s, runtime=_rt(llm=llm))
    assert "SYS" in llm.system and "BODY" in llm.system
    assert u["prompt_versions"]["triage"]["version"] == 2
    assert u["skills_snapshot"]["triage"][0]["name"] == "taint"


def test_triage_disabled_passes_through():
    s = new_state("/r", OSS=False)
    s["engine_findings"] = [{"rule_id": "x", "line": 1, "confidence": 0.5}]
    u = run_triage(s, runtime=_rt(enabled=False))
    assert u["triaged_findings"][0]["triage"]["rationale"].startswith("agent disabled")


def test_poc_capability_forces_plausible(monkeypatch, tmp_path):
    monkeypatch.setenv("CODESENTRY_POC_RUN", "sandbox")
    monkeypatch.setenv("CODESENTRY_WORK_DIR", str(tmp_path))

    class L:
        def complete(self, *a, **k):
            return '{"exploit_chain": [], "poc_script": "print(1)", "notes": ""}'

    s = new_state("/r", OSS=False)
    s["triaged_findings"] = [{"rule_id": "x", "cwe": 134, "line": 1, "file": "a.c", "confidence": 0.8}]
    u = run_poc_gen(s, runtime=_rt("poc_gen", llm=L(), caps={"poc_exec": False}))
    assert u["poc_results"]["x@1"]["verdict"] == "plausible"
    assert "poc_exec" in u["poc_results"]["x@1"]["execution_log"]


def test_disabled_non_llm_node_is_skipped(monkeypatch):
    from codesentry.orchestrator.graph import _wrap

    monkeypatch.setattr(
        "codesentry.control.agent_config.get_agent_config",
        lambda name: {"enabled": False},
    )
    called = {"n": 0}

    def stub(state):
        called["n"] += 1
        return {}

    out = _wrap("scan", stub, {"scan_id": 0, "budget": None})(new_state("/r", OSS=False))
    assert called["n"] == 0
    assert any("agent disabled" in m for m in out["messages"])


def test_snapshot_agents_shape():
    prompts, skills, llms = _snapshot_agents()
    assert set(prompts) == {"recon", "scan", "retrieval", "triage", "poc_gen", "report"}
    for v in prompts.values():
        assert "version" in v and "fallback" in v
    assert isinstance(skills, dict) and isinstance(llms, dict)
