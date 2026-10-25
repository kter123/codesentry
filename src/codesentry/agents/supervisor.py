"""统一 Supervisor：白名单动作调度，不直接下漏洞结论。"""

from __future__ import annotations


def run_supervisor(state: dict, runtime=None, llm=None) -> dict:
    from codesentry.config import get_settings
    from codesentry.control.audit_paths import coverage
    from codesentry.orchestrator.events import publish_event

    scan_id = int(state.get("scan_id") or 0)
    settings = get_settings()
    budget = state.get("budget") or {}
    previous = state.get("supervisor") or {}
    audit_repo_done = bool(previous.get("audit_repo_done"))
    cover = {}
    if scan_id:
        try:
            cover = coverage(scan_id)
        except Exception:  # noqa: BLE001
            cover = {}
    pending = int(cover.get("pending", 0) or 0)
    rounds = int(cover.get("rounds", state.get("audit_round") or 0) or 0)
    candidates = len(state.get("candidate_findings") or [])
    path_results = state.get("path_results") or []

    if budget.get("phase") == "breach":
        action, reason = "report", "预算熔断"
    elif pending > 0 and rounds < int(settings.audit_max_rounds):
        action, reason = "audit_paths", f"{pending} 条待审路径"
    elif not audit_repo_done and candidates == 0 and not path_results:
        action, reason = "audit_repo", "无路径候选，执行一次仓库级 Agent 审计"
    elif candidates > 0:
        action, reason = "triage", f"{candidates} 条候选待判定"
    elif not previous.get("triaged"):
        action, reason = "triage", "没有候选，执行一次空 Triage 收敛"
    else:
        action, reason = "report", "没有更多候选"

    payload = {"action": action, "reason": reason, "pending": pending,
               "rounds": rounds, "candidates": candidates,
               "budget_phase": budget.get("phase")}
    if scan_id:
        publish_event(scan_id, "supervisor.decision", agent="supervisor",
                      phase="supervisor", payload=payload)
    sup = {**previous, **payload,
           "audit_repo_done": audit_repo_done or action == "audit_repo",
           "triaged": bool(previous.get("triaged")) or action == "triage"}
    return {"supervisor": sup, "phase": action,
            "messages": [*(state.get("messages") or []), f"supervisor: {action} ({reason})"]}


def route_supervisor(state: dict) -> str:
    action = str((state.get("supervisor") or {}).get("action") or "report")
    return {"audit_paths": "audit_plan", "audit_repo": "audit_finalize",
            "triage": "triage", "report": "report", "finish": "report"}.get(action, "report")
