import json

from codesentry.agents.tools import run_tool_loop
from codesentry.agents.triage import triage_one
from codesentry.orchestrator.budget import BudgetGuard


class SeqLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def complete(self, system, user, model_role="deep"):
        self.calls += 1
        return self.responses.pop(0)


def test_tool_loop_executes_and_stops():
    llm = SeqLLM([
        json.dumps({"tool_calls": [{"tool": "read_source", "args": {"path": "a.py"}}]}),
        json.dumps({"verdict": "keep", "confidence": 0.9, "rationale": "r", "fix_advice": "f"}),
    ])
    called = []
    text, trace = run_tool_loop(
        llm, "sys", "user",
        tools={"read_source": lambda path: called.append(path) or "line 1: code"},
        max_iterations=4,
    )
    assert "verdict" in text
    assert called == ["a.py"]
    assert len(trace) == 2
    assert llm.calls == 2


def test_tool_loop_respects_max_iterations():
    llm = SeqLLM([json.dumps({"tool_calls": [{"tool": "read_source", "args": {"path": "a.py"}}]})] * 3)
    text, _trace = run_tool_loop(
        llm, "sys", "user",
        tools={"read_source": lambda path: "x"},
        max_iterations=2,
    )
    assert llm.calls == 2
    assert "tool_calls" in text


def test_triage_one_attaches_tool_trace():
    llm = SeqLLM([
        json.dumps({"tool_calls": [{"tool": "read_source", "args": {"path": "a.py"}}]}),
        json.dumps({"verdict": "keep", "confidence": 0.8, "rationale": "r", "fix_advice": "f"}),
    ])
    out = triage_one(
        llm, {"rule_id": "x", "line": 1}, {},
        tools={"read_source": lambda path: "code"}, max_iterations=3,
    )
    assert out["verdict"] == "keep"
    assert out["tool_trace"][0]["tool"] == "read_source"


def test_agent_budget_override():
    guard = BudgetGuard(0)
    guard.record(tokens=100, cost_usd=0.2, agent="triage")
    assert guard.over_agent("triage", {"max_tokens": 100}) is True
    assert guard.over_agent("triage", {"max_cost_usd": 0.1}) is True
    assert guard.over_agent("scan", {"max_tokens": 100}) is False
    state = guard.to_state()
    assert state["agents"]["tokens"]["triage"] == 100
