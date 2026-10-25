"""LangGraph 节点注册表（M6.1）：节点元数据与默认可调用对象。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class NodeSpec:
    name: str
    description: str
    requires_llm: bool = False
    required: bool = False


NODE_SPECS: dict[str, NodeSpec] = {
    "recon": NodeSpec("recon", "仓库画像与扫描计划", required=True),
    "graph_build": NodeSpec("graph_build", "代码图构建（增量）", required=True),
    "scan": NodeSpec("scan", "引擎执行并转为图增量", requires_llm=False),
    "supervisor": NodeSpec("supervisor", "统一调度与预算/轮次决策", requires_llm=False),
    "verification": NodeSpec("verification", "Harness 生成与沙箱验证", requires_llm=True),
    "audit": NodeSpec("audit", "Agent 主动代码审计", requires_llm=True),
    "triage": NodeSpec("triage", "Agent 对抗性验证与降噪", requires_llm=True),
    "deploy": NodeSpec("deploy", "Agent 自主部署", requires_llm=True),
    "poc_gen": NodeSpec("poc_gen", "PoC 生成与验证", requires_llm=True),
    "report": NodeSpec("report", "报告生成", required=True),
}


def get_node(name: str) -> NodeSpec:
    try:
        return NODE_SPECS[name]
    except KeyError as exc:
        raise KeyError(f"unknown node: {name}") from exc


def all_nodes() -> list[NodeSpec]:
    return list(NODE_SPECS.values())


def default_nodes() -> dict[str, Callable]:
    """懒加载默认节点函数，避免 registry 导入 agents 造成循环。"""
    from codesentry.agents.audit import run_audit_agent
    from codesentry.agents.deploy_agent import run_deploy_agent
    from codesentry.agents.graph_builder import run_graph_build
    from codesentry.agents.poc_gen import run_poc_gen
    from codesentry.agents.recon import run_recon
    from codesentry.agents.report import run_report
    from codesentry.agents.scan import run_scan_agent
    from codesentry.agents.supervisor import run_supervisor
    from codesentry.agents.triage import run_triage

    def default_report(state):
        return run_report(state, state.get("report_dir") or "work/report")

    return {
        "recon": run_recon,
        "graph_build": run_graph_build,
        "scan": run_scan_agent,
        "audit": run_audit_agent,
        "triage": run_triage,
        "deploy": run_deploy_agent,
        "poc_gen": run_poc_gen,
        "report": default_report,
        "supervisor": run_supervisor,
    }
