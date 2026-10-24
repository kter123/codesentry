import pytest

from codesentry.agents.state import new_state
from codesentry.orchestrator.graph import build_graph
from codesentry.orchestrator.registry import all_nodes, default_nodes, get_node


def test_registry_has_six_nodes():
    names = {n.name for n in all_nodes()}
    assert names == {"recon", "graph_build", "scan", "audit", "triage", "deploy", "poc_gen", "report"}
    assert get_node("triage").requires_llm is True
    assert get_node("recon").required is True


def test_unknown_node_raises():
    with pytest.raises(KeyError):
        get_node("nope")


def test_default_nodes_callable():
    d = default_nodes()
    assert set(d) == {"recon", "graph_build", "scan", "audit", "triage", "deploy", "poc_gen", "report"}
    assert all(callable(fn) for fn in d.values())


def test_build_graph_with_defaults_compiles():
    g = build_graph(checkpointer=None, scan_id_holder={"scan_id": 0, "budget": None})
    assert g is not None


def test_explicit_override_still_works():
    def triage(state, runtime=None, llm=None):
        return {"triaged_findings": [], "phase": "poc_gen"}

    g = build_graph(
        scan_agent=lambda s: {"engine_findings": []},
        retrieval_agent=lambda s: {"evidence": {}},
        triage_agent=triage,
        poc_agent=lambda s: {"poc_results": {}},
        report_agent_fn=lambda s: {"phase": "done"},
        recon_agent=lambda s: {"profile": {"languages": ["python"]}},
    )
    final = g.invoke(new_state("/r", OSS=False), config={"recursion_limit": 20})
    assert final["phase"] == "done"
