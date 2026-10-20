"""LangGraph Send 并行 fan-out 验证（M6）：TriageAgent 按 finding 并行 + 预算回流。"""

import time
from typing import Annotated

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from typing_extensions import TypedDict

from codesentry.agents.triage import run_triage


class FanState(TypedDict, total=False):
    findings: list
    results: Annotated[list, lambda a, b: (a or []) + (b or [])]


def _fan_out(state: dict) -> list[Send]:
    return [Send("verify_one", {"finding": f}) for f in state.get("findings", [])]


def _verify_one(state: dict) -> dict:
    time.sleep(0.05)
    return {"results": [{"rule_id": state["finding"]["rule_id"], "verdict": "keep"}]}


def _merge(state: dict) -> dict:
    return {}


def _build():
    g = StateGraph(FanState)
    g.add_node("verify_one", _verify_one)
    g.add_node("merge", _merge)
    g.add_conditional_edges(START, _fan_out, ["verify_one"])
    g.add_edge("verify_one", "merge")
    g.add_edge("merge", END)
    return g.compile()


def test_send_parallel_is_faster_than_serial():
    g = _build()
    findings = [{"rule_id": f"r{i}", } for i in range(20)]
    started = time.monotonic()
    final = g.invoke({"findings": findings, "results": []}, config={"recursion_limit": 50})
    parallel_s = time.monotonic() - started
    ids = {r["rule_id"] for r in final["results"]}
    assert ids == {f"r{i}" for i in range(20)}
    expected_serial = 20 * 0.05
    assert parallel_s < expected_serial, f"parallel {parallel_s:.2f}s must beat serial ~{expected_serial:.2f}s"


def test_triage_accepts_runtime_signature():
    """run_triage 声明 runtime 参数，注册表与注入层可用。"""
    import inspect

    params = inspect.signature(run_triage).parameters
    assert "runtime" in params and "llm" in params
