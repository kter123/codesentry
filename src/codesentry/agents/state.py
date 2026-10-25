"""AuditState 共享状态（agent.md §7.1）+ Agent 名常量。"""

from datetime import UTC
from operator import add
from typing import Annotated, TypedDict

AGENT_NAMES = ("recon", "scan", "audit", "triage", "deploy", "poc_gen", "report")

# Supervisor 介入点（§7.3）
INTERRUPT_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
INTERRUPT_ENGINE_CONFLICT = "engine_conflict"
INTERRUPT_AGENT_FAILURE = "agent_failure"

MAX_REPLANS = 3  # 审查重点 1：重规划上限，避免无限循环


class AuditState(TypedDict, total=False):
    # 输入
    repo_path: str
    license_declaration: dict  # {OSS: bool, declared_at: str}
    diff_scope: dict | None  # {base, head, files: [...]} 增量模式
    # recon
    profile: dict  # ScanProfile as dict
    # 代码图（G1）
    graph_build_id: int
    graph_stats: dict
    # 引擎
    engine_findings: list  # 兼容旧调用：引擎候选（不再作为最终 finding）
    engine_hints: list  # 引擎转图后的 hint（审计线索）
    engine_results_meta: list  # 降级/状态元数据（报告用）
    graph_delta: dict  # 引擎 → 图的增量统计
    # 审计
    candidate_findings: list  # AuditAgent 产出的候选
    audit: dict  # audit 元数据（tool_trace/数量）
    audit_feedback: str  # triage → audit 补查指令
    # 路径中心审计（2026-10-24）
    audit_paths: list  # 本批待审路径（由 audit_plan 覆盖）
    path_results: Annotated[list[dict], add]  # Send 并行结果合并
    audit_round: int
    audit_batch: int
    coverage: dict
    supervisor: dict
    # triage
    triaged_findings: list  # 保留/降级/否决后（dict）
    evidence: dict  # finding_iid -> {'code_slices': [...], 'kb': [...], 'vuln_cases': [...]}
    # poc
    poc_results: dict  # finding_iid -> {exploit_chain, poc_file, verdict, execution_log}
    # deploy（M6.2）
    deploy_status: str
    deploy_log: str
    target_url: str
    deploy: dict
    # 预算
    budget: dict  # {tokens, tool_calls, cost_usd, phase: ok|warn|breach}
    # 可复现（NFR-2）
    prompt_versions: dict  # agent -> version
    skills_snapshot: dict  # agent -> [{name, version, sha}]
    # 控制
    phase: str  # recon|scan|retrieval|triage|poc_gen|human_review|report|done
    replan_count: int
    messages: list  # 告警/审计消息（截断告警、回退告警…）
    scan_id: int  # 落库 scans.id（M3 起持久化）


def new_state(repo_path: str, OSS: bool, scan_id: int | None = None) -> AuditState:
    from datetime import datetime

    return AuditState(
        repo_path=repo_path,
        license_declaration={"OSS": OSS, "declared_at": datetime.now(UTC).isoformat(timespec="seconds")},
        diff_scope=None,
        profile={},
        graph_build_id=0,
        graph_stats={},
        engine_findings=[],
        engine_hints=[],
        engine_results_meta=[],
        graph_delta={},
        candidate_findings=[],
        audit={},
        audit_feedback="",
        audit_paths=[],
        path_results=[],
        audit_round=0,
        audit_batch=0,
        coverage={},
        triaged_findings=[],
        evidence={},
        poc_results={},
        deploy_status="",
        deploy_log="",
        target_url="",
        deploy={},
        budget={"tokens": 0, "tool_calls": 0, "cost_usd": 0.0, "phase": "ok"},
        prompt_versions={},
        skills_snapshot={},
        phase="recon",
        replan_count=0,
        messages=[],
        scan_id=scan_id or 0,
    )
