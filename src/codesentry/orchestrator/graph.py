"""LangGraph 图组装（agent.md D4/§7.3）+ PostgresSaver checkpoint。

主链路确定性：recon → scan → retrieval → triage → poc_gen → (human_review 可选) → report。
Supervisor 介入点（3 类）：triage「证据不足」→ 补查 retrieval 一次；引擎冲突 → supervisor 决策；
agent 失败 → 重规划（上限 MAX_REPLANS=3，超出熔断进 report）。
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from codesentry.agents.recon import run_recon
from codesentry.agents.state import MAX_REPLANS, AuditState
from codesentry.orchestrator.telemetry import node_run


def _wrap(node_name: str, fn, scan_id_holder: dict):
    def inner(state: AuditState) -> dict:
        sid = scan_id_holder.get("scan_id") or 0
        with node_run(sid, node_name):
            update = fn(state)
        bc = scan_id_holder.get("budget")
        if bc is not None:
            # budget 复本入 state（NFR 遥测）
            update = {**update, "budget": bc.to_state()}
        return update

    inner.__name__ = fn.__name__
    return inner


def route_after_triage(state: AuditState) -> str:
    """Supervisor 条件边 1：triage 报证据不足 → 补查 retrieval；正常 → poc_gen。"""
    messages = state.get("messages") or []
    insufficient = any("insufficient_evidence" in str(m) for m in messages[-3:])
    state["replan_count"] = (state.get("replan_count") or 0) + (1 if insufficient else 0)
    if insufficient and (state.get("replan_count") or 0) <= MAX_REPLANS:
        return "retrieval"  # 补查一次
    return "poc_gen"


def route_after_poc(state: AuditState) -> str:
    from codesentry.config import get_settings

    if get_settings().human_review:
        return "human_review"
    return "report"


def build_graph(
    *,
    scan_agent,
    retrieval_agent,
    triage_agent,
    poc_agent,
    report_agent_fn,
    checkpointer: BaseCheckpointSaver | None = None,
    scan_id_holder: dict | None = None,
    human_review_node: Any | None = None,
) -> Any:
    holder = scan_id_holder or {"scan_id": 0, "budget": None}
    g = StateGraph(AuditState)

    g.add_node("recon", _wrap("recon", run_recon, holder))
    g.add_node("scan", _wrap("scan", scan_agent, holder))
    g.add_node("retrieval", _wrap("retrieval", retrieval_agent, holder))
    g.add_node("triage", _wrap("triage", triage_agent, holder))
    g.add_node("poc_gen", _wrap("poc_gen", poc_agent, holder))
    g.add_node("report", _wrap("report", report_agent_fn, holder))
    if human_review_node is not None:
        g.add_node("human_review", human_review_node)

    g.add_edge(START, "recon")
    g.add_edge("recon", "scan")
    g.add_edge("scan", "retrieval")
    g.add_edge("retrieval", "triage")
    g.add_conditional_edges("triage", route_after_triage, {"retrieval": "retrieval", "poc_gen": "poc_gen"})
    g.add_conditional_edges("poc_gen", route_after_poc, {"human_review": "human_review", "report": "report"} if human_review_node is not None else {"report": "report"})
    if human_review_node is not None:
        g.add_edge("human_review", "report")
    g.add_edge("report", END)

    if checkpointer is not None:
        return g.compile(checkpointer=checkpointer)
    return g.compile()
