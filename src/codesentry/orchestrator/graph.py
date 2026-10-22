"""LangGraph 图组装（agent.md D4/§7.3）+ PostgresSaver checkpoint。

主链路确定性：recon → scan → retrieval → triage → poc_gen → (human_review 可选) → report。
Supervisor 介入点（3 类）：triage「证据不足」→ 补查 retrieval 一次；引擎冲突 → supervisor 决策；
agent 失败 → 重规划（上限 MAX_REPLANS=3，超出熔断进 report）。
"""

from __future__ import annotations

import inspect
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from codesentry.agents.state import MAX_REPLANS, AuditState
from codesentry.orchestrator.telemetry import node_run


def _wrap(node_name: str, fn, scan_id_holder: dict):
    def inner(state: AuditState) -> dict:
        sid = scan_id_holder.get("scan_id") or 0
        bc = scan_id_holder.get("budget")
        if node_name in {"recon", "scan", "retrieval", "report"}:
            try:
                from codesentry.control.agent_config import get_agent_config

                if not get_agent_config(node_name).get("enabled", True):
                    with node_run(sid, node_name, status_override="skipped"):
                        pass
                    skip: dict = {
                        "messages": [*(state.get("messages") or []), f"{node_name}: agent disabled"]
                    }
                    if node_name == "report":
                        skip["phase"] = "done"
                    return skip
            except Exception:  # noqa: BLE001, S110 - 配置不可用时按启用处理
                pass
        kwargs: dict[str, Any] = {}
        params: Any
        status_override: str | None = None
        runtime = None
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            params = {}
        if "runtime" in params:
            runtime = None
            try:
                from codesentry.agents.runtime import prepare_agent

                runtime = prepare_agent(
                    node_name, scan_id=sid, snapshot=scan_id_holder.get("snapshot")
                )
            except Exception:  # noqa: BLE001 - runtime 解析失败时节点降级
                runtime = None
            kwargs["runtime"] = runtime
            if "llm" in params:
                kwargs["llm"] = runtime.llm if runtime is not None else None
            if runtime is not None and not getattr(runtime, "enabled", True):
                status_override = "skipped"
        elif "llm" in params:
            kwargs["llm"] = None
        override: dict = {}
        if runtime is not None:
            override = getattr(runtime, "budget_override", {}) or {}
        elif bc is not None:
            try:
                from codesentry.control.agent_config import get_agent_config

                override = get_agent_config(node_name).get("budget_override") or {}
            except Exception:  # noqa: BLE001
                override = {}
        if bc is not None and override and bc.over_agent(node_name, override):
            with node_run(sid, node_name, status_override="skipped"):
                pass
            return {
                "messages": [
                    *(state.get("messages") or []),
                    f"{node_name}: agent budget_override exceeded",
                ]
            }
        with node_run(sid, node_name, status_override=status_override) as _run:
            update = fn(state, **kwargs)
            tokens_used = _get_last_tokens()
            cost_used = _get_last_cost()
            _run.tokens = tokens_used
        # LLM token/cost 回流（NFR-2 / 预算熔断）：agents 的 LLMClient 用量进台账
        if bc is not None and (tokens_used or cost_used):
            bc.record(tokens=tokens_used, cost_usd=cost_used, phase=node_name, agent=node_name)
        if sid:
            try:
                from codesentry.orchestrator.artifacts import summarize_state, write_artifact

                seq = int(scan_id_holder.get("artifact_seq") or 0) + 1
                prev = str(scan_id_holder.get("last_sha") or "")
                model = ""
                if runtime is not None and runtime.llm is not None:
                    model = str((runtime.llm.last_meta or {}).get("model") or "")
                digest = write_artifact(
                    scan_id=sid, seq=seq, node=node_name,
                    input_obj=summarize_state(state), output_obj=update,
                    model=model, tokens=tokens_used, prev_sha256=prev,
                )
                if digest:
                    scan_id_holder["artifact_seq"] = seq
                    scan_id_holder["last_sha"] = digest
            except Exception:  # noqa: BLE001, S110 - 审查链失败不阻塞扫描
                pass
        if bc is not None:
            # budget 复本入 state（NFR 遥测）
            update = {**update, "budget": bc.to_state()}
        return update

    inner.__name__ = fn.__name__
    return inner


def _get_last_tokens() -> int:
    """读取当前 LLMClient 本次节点用掉的 tokens（contextvar 累计，无 client 时 0）。"""
    try:
        from codesentry.agents.llm import current_tokens_delta

        return current_tokens_delta()
    except Exception:  # noqa: BLE001 - 遥测失败不阻塞
        return 0


def _get_last_cost() -> float:
    try:
        from codesentry.agents.llm import current_cost_delta

        return current_cost_delta()
    except Exception:  # noqa: BLE001 - 遥测失败不阻塞
        return 0.0


def route_after_triage(state: AuditState) -> str:
    """Supervisor 条件边 1：预算熔断 → report；证据不足 → 补查；正常 → poc_gen。"""
    if (state.get("budget") or {}).get("phase") == "breach":
        return "report"
    messages = state.get("messages") or []
    insufficient = any("insufficient_evidence" in str(m) for m in messages[-3:])
    state["replan_count"] = (state.get("replan_count") or 0) + (1 if insufficient else 0)
    if insufficient and (state.get("replan_count") or 0) <= MAX_REPLANS:
        return "retrieval"  # 补查一次
    return "poc_gen"


def route_after_poc(state: AuditState) -> str:
    from codesentry.config import get_settings

    if (state.get("budget") or {}).get("phase") == "breach":
        return "report"
    if get_settings().human_review:
        return "human_review"
    return "report"


def build_graph(
    *,
    scan_agent=None,
    retrieval_agent=None,
    triage_agent=None,
    poc_agent=None,
    report_agent_fn=None,
    recon_agent=None,
    deploy_agent=None,
    checkpointer: BaseCheckpointSaver | None = None,
    scan_id_holder: dict | None = None,
    human_review_node: Any | None = None,
) -> Any:
    holder = scan_id_holder or {"scan_id": 0, "budget": None}
    if any(x is None for x in (scan_agent, retrieval_agent, triage_agent, poc_agent, report_agent_fn, recon_agent)):
        from codesentry.orchestrator.registry import default_nodes

        defaults = default_nodes()
        scan_agent = scan_agent or defaults["scan"]
        retrieval_agent = retrieval_agent or defaults["retrieval"]
        triage_agent = triage_agent or defaults["triage"]
        poc_agent = poc_agent or defaults["poc_gen"]
        report_agent_fn = report_agent_fn or defaults["report"]
        recon_agent = recon_agent or defaults["recon"]

    g = StateGraph(AuditState)

    g.add_node("recon", _wrap("recon", recon_agent, holder))
    g.add_node("scan", _wrap("scan", scan_agent, holder))
    g.add_node("retrieval", _wrap("retrieval", retrieval_agent, holder))
    g.add_node("triage", _wrap("triage", triage_agent, holder))
    if deploy_agent is not None:
        g.add_node("deploy", _wrap("deploy", deploy_agent, holder))
    g.add_node("poc_gen", _wrap("poc_gen", poc_agent, holder))
    g.add_node("report", _wrap("report", report_agent_fn, holder))
    if human_review_node is not None:
        g.add_node("human_review", human_review_node)

    g.add_edge(START, "recon")
    g.add_edge("recon", "scan")
    g.add_edge("scan", "retrieval")
    g.add_edge("retrieval", "triage")
    if deploy_agent is not None:
        def _route_triage_with_deploy(state: AuditState) -> str:
            nxt = route_after_triage(state)
            return "deploy" if nxt == "poc_gen" else nxt

        g.add_conditional_edges(
            "triage", _route_triage_with_deploy,
            {"retrieval": "retrieval", "deploy": "deploy", "report": "report"},
        )
        g.add_edge("deploy", "poc_gen")
    else:
        g.add_conditional_edges("triage", route_after_triage,
                                {"retrieval": "retrieval", "poc_gen": "poc_gen", "report": "report"})
    g.add_conditional_edges("poc_gen", route_after_poc, {"human_review": "human_review", "report": "report"} if human_review_node is not None else {"report": "report"})
    if human_review_node is not None:
        g.add_edge("human_review", "report")
    g.add_edge("report", END)

    if checkpointer is not None:
        return g.compile(checkpointer=checkpointer)
    return g.compile()
