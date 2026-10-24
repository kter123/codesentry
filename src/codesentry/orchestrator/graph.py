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
    cfg_name = "audit" if node_name == "audit_path" else node_name

    def inner(state: AuditState) -> dict:
        sid = scan_id_holder.get("scan_id") or 0
        bc = scan_id_holder.get("budget")
        if cfg_name in {"recon", "scan", "audit", "deploy", "report"}:
            try:
                from codesentry.control.agent_config import get_agent_config

                if not get_agent_config(cfg_name).get("enabled", True):
                    with node_run(sid, node_name, status_override="skipped"):
                        pass
                    if node_name == "audit_path":
                        return {}
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
                    cfg_name, scan_id=sid, snapshot=scan_id_holder.get("snapshot")
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

                override = get_agent_config(cfg_name).get("budget_override") or {}
            except Exception:  # noqa: BLE001
                override = {}
        if bc is not None and override and bc.over_agent(cfg_name, override):
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
        if bc is not None and node_name != "audit_path":
            # Send 并行分支不能同时写非 reducer 的 budget；汇总节点再写
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
    """预算熔断 → report；证据不足 → audit 补查；正常 → deploy/poc。"""
    if (state.get("budget") or {}).get("phase") == "breach":
        return "report"
    messages = state.get("messages") or []
    insufficient = bool(state.get("audit_feedback")) or any(
        "insufficient_evidence" in str(m) for m in messages[-3:]
    )
    replans = int(state.get("replan_count") or 0)
    if insufficient and replans < MAX_REPLANS:
        state["replan_count"] = replans + 1
        return "audit"
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
    graph_build_agent=None,
    audit_agent=None,
    deploy_agent=None,
    checkpointer: BaseCheckpointSaver | None = None,
    scan_id_holder: dict | None = None,
    human_review_node: Any | None = None,
) -> Any:
    holder = scan_id_holder or {"scan_id": 0, "budget": None}
    if any(x is None for x in (scan_agent, triage_agent, poc_agent, report_agent_fn, recon_agent)):
        from codesentry.orchestrator.registry import default_nodes

        defaults = default_nodes()
        scan_agent = scan_agent or defaults["scan"]
        triage_agent = triage_agent or defaults["triage"]
        poc_agent = poc_agent or defaults["poc_gen"]
        report_agent_fn = report_agent_fn or defaults["report"]
        recon_agent = recon_agent or defaults["recon"]
    from codesentry.orchestrator.registry import default_nodes

    defaults = default_nodes()
    graph_build_agent = graph_build_agent or defaults["graph_build"]
    audit_agent = audit_agent or defaults["audit"]
    if deploy_agent is None:
        deploy_agent = defaults["deploy"]

    g = StateGraph(AuditState)

    from codesentry.agents.path_audit_nodes import (
        route_after_collect,
        route_audit,
        run_audit_collect,
        run_audit_finalize,
        run_audit_path,
        run_audit_plan,
        run_path_build,
    )

    g.add_node("recon", _wrap("recon", recon_agent, holder))
    g.add_node("graph_build", _wrap("graph_build", graph_build_agent, holder))
    g.add_node("scan", _wrap("scan", scan_agent, holder))
    g.add_node("path_build", _wrap("path_build", run_path_build, holder))
    g.add_node("audit_plan", _wrap("audit_plan", run_audit_plan, holder))
    g.add_node("audit_path", _wrap("audit_path", run_audit_path, holder))
    g.add_node("audit_collect", _wrap("audit_collect", run_audit_collect, holder))
    g.add_node("audit_finalize", _wrap("audit", audit_agent or run_audit_finalize, holder))
    g.add_node("triage", _wrap("triage", triage_agent, holder))
    g.add_node("deploy", _wrap("deploy", deploy_agent, holder))
    g.add_node("poc_gen", _wrap("poc_gen", poc_agent, holder))
    g.add_node("report", _wrap("report", report_agent_fn, holder))
    if human_review_node is not None:
        g.add_node("human_review", human_review_node)

    g.add_edge(START, "recon")
    g.add_edge("recon", "graph_build")
    g.add_edge("graph_build", "scan")
    g.add_edge("scan", "path_build")
    g.add_edge("path_build", "audit_plan")
    def _route_audit(state: AuditState):
        if not (state.get("audit_paths") or []) and audit_agent is not None:
            return "audit_finalize"
        return route_audit(dict(state))

    g.add_conditional_edges(
        "audit_plan", _route_audit,
        {"audit_path": "audit_path", "triage": "triage", "audit_finalize": "audit_finalize"},
    )
    g.add_edge("audit_path", "audit_collect")
    g.add_conditional_edges(
        "audit_collect", route_after_collect,
        {"audit_plan": "audit_plan", "triage": "triage", "audit_finalize": "audit_finalize"},
    )
    g.add_edge("audit_finalize", "triage")

    def _route_triage(state: AuditState) -> str:
        nxt = route_after_triage(state)
        if nxt == "audit":
            # 路径审计已多轮；Triage 后不再回环，避免无 pending 时空转
            nxt = "poc_gen"
        return "deploy" if nxt == "poc_gen" else nxt

    g.add_conditional_edges(
        "triage", _route_triage,
        {"audit_plan": "audit_plan", "deploy": "deploy", "report": "report"},
    )
    g.add_edge("deploy", "poc_gen")
    g.add_conditional_edges("poc_gen", route_after_poc, {"human_review": "human_review", "report": "report"} if human_review_node is not None else {"report": "report"})
    if human_review_node is not None:
        g.add_edge("human_review", "report")
    g.add_edge("report", END)

    if checkpointer is not None:
        return g.compile(checkpointer=checkpointer)
    return g.compile()
