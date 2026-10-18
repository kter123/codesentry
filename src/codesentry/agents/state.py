"""AuditState 共享状态（agent.md §7.1）+ Agent 名常量。"""

from datetime import UTC
from typing import TypedDict

AGENT_NAMES = ("recon", "scan", "retrieval", "triage", "poc_gen", "report")

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
    # 引擎
    engine_findings: list  # list[dict(Finding)]
    engine_results_meta: list  # 降级/状态元数据（报告用）
    # triage
    triaged_findings: list  # 保留/降级/否决后（dict）
    evidence: dict  # finding_iid -> {'code_slices': [...], 'kb': [...], 'vuln_cases': [...]}
    # poc
    poc_results: dict  # finding_iid -> {exploit_chain, poc_file, verdict, execution_log}
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
        engine_findings=[],
        engine_results_meta=[],
        triaged_findings=[],
        evidence={},
        poc_results={},
        budget={"tokens": 0, "tool_calls": 0, "cost_usd": 0.0, "phase": "ok"},
        prompt_versions={},
        skills_snapshot={},
        phase="recon",
        replan_count=0,
        messages=[],
        scan_id=scan_id or 0,
    )
