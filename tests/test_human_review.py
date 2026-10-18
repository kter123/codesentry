"""人工复核 interrupt + resume（FR-9/D20）。"""

import pytest
from langgraph.checkpoint.memory import MemorySaver

from codesentry.agents.state import new_state
from codesentry.orchestrator.graph import build_graph
from codesentry.orchestrator.human_review import human_review_node


@pytest.fixture(autouse=True)
def _hr_on(monkeypatch):
    monkeypatch.setenv("CODESENTRY_HUMAN_REVIEW", "true")
    # graph 测试注入 stub LLM —— get_settings 的真 env 被覆盖为无效占位
    monkeypatch.setenv("CODESENTRY_MODEL_BASE_URL", "http://127.0.0.1:59999/v1")
    monkeypatch.setenv("CODESENTRY_FAST_MODEL", "f")
    monkeypatch.setenv("CODESENTRY_DEEP_MODEL", "d")
    monkeypatch.setenv("CODESENTRY_MODEL_API_KEY", "")


def test_human_review_reject_drops_finding(tmp_path):
    repo = tmp_path / "r1"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    from codesentry.agents.report import run_report

    triaged_f = [{"rule_id": "x/1", "cwe": 918, "severity": "high", "confidence": 0.8,
                  "file": "a.py", "line": 1, "message": "m", "engine": "semgrep",
                  "triage": {"verdict": "keep", "confidence": 0.8, "rationale": "", "fix_advice": ""}}]

    g = build_graph(
        scan_agent=lambda s: {"engine_findings": [], "phase": "retrieval"},
        retrieval_agent=lambda s: {"evidence": {}, "phase": "triage"},
        triage_agent=lambda s: {"triaged_findings": triaged_f, "phase": "poc_gen"},
        poc_agent=lambda s: {"poc_results": {}, "phase": "human_review"},
        report_agent_fn=lambda s, out=str(tmp_path / "hr-rep"): run_report(s, out),
        checkpointer=MemorySaver(),
        human_review_node=lambda s: human_review_node(s),
    )
    st = new_state(str(repo), OSS=False)
    st["triaged_findings"] = triaged_f
    cfg = {"configurable": {"thread_id": "t-hr-1"}, "recursion_limit": 25}
    # interrupt at human_review
    from langgraph.types import Command

    res = g.invoke(st, config=cfg)
    # 状态里应反映已处理（单节点 interrupt 在 invoke 流程内，直接给决策）
    state = g.get_state(cfg)
    nxt = state.next if hasattr(state, "next") else ()
    if nxt:  # 真的 interrupt 了 → 注入决策
        decisions = [{"rule_id": "x/1", "line": 1, "verdict": "reject"}]
        res = g.invoke(Command(resume=decisions), config=cfg)
    assert res["phase"] == "done"
    assert not res["triaged_findings"]  # 驳回的不落报告
