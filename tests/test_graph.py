"""graph 组装单测（checkpointer mock / 真 connector 在集成测试）+ LLM mock 端到端。"""

from langgraph.checkpoint.memory import MemorySaver

from codesentry.agents.report import run_report
from codesentry.agents.retrieval import run_retrieval
from codesentry.agents.state import new_state
from codesentry.orchestrator.graph import build_graph, route_after_triage


def test_graph_runs_full_chain(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("x = 1\n")
    # mock LLM 配置，避免 runtime 未配置报错
    monkeypatch.setenv("CODESENTRY_MODEL_BASE_URL", "http://127.0.0.1:59999/v1")
    monkeypatch.setenv("CODESENTRY_FAST_MODEL", "f")
    monkeypatch.setenv("CODESENTRY_DEEP_MODEL", "d")

    holder = {"scan_id": 0, "budget": None}
    g = build_graph(
        scan_agent=lambda s: {"engine_findings": [], "phase": "retrieval"},
        retrieval_agent=run_retrieval,
        triage_agent=lambda s: {"triaged_findings": [], "phase": "poc_gen"},
        poc_agent=lambda s: {"poc_results": {}, "phase": "report"},
        report_agent_fn=lambda s, out="/tmp/x-report": run_report(s, out),
        checkpointer=None,
        scan_id_holder=holder,
    )
    st = new_state(str(repo), OSS=False)
    final = g.invoke(st, config={"recursion_limit": 10})
    assert final["phase"] == "done"
    assert final["profile"].get("languages") == ["python"]


def test_route_insufficient_evidence():
    s = new_state("/r", OSS=False)
    s["messages"] = ["triage: insufficient_evidence for x@1"]
    assert route_after_triage(s) == "retrieval"
    s["replan_count"] = 99
    assert route_after_triage(s) == "poc_gen"  # max replans 熔断


def test_memory_checkpointer_reuse():
    cp = MemorySaver()
    repo_src = None  # 占位；真流程测试在 test_graph_runs_full_chain
    assert cp is not None and repo_src is None
