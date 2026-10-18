"""人工复核中断（agent.md FR-9/D20）：report 前 interrupt；恢复由复核决策驱动。

LangGraph interrupt_before=['report']；WebUI/CLI 复核队列读取 interrupt 状态的 AuditState，
decisions: [{rule_id, line, verdict: approve|reject|confidence}], 应用后 resume graph。
"""

from langgraph.types import interrupt as lg_interrupt


def human_review_node(state: dict) -> dict:
    """interrupt 节点：把三档待复核信息打包交给外界（WebUI 队列）。
    决策在 resume 时通过 Command 注入——这里读取 decisions 并写回 state。"""
    from langgraph.types import Command

    pending = [
        {"rule_id": t.get("rule_id"), "line": t.get("line"), "cwe": t.get("cwe"),
         "severity": t.get("severity"), "confidence": t.get("confidence"),
         "file": t.get("file"), "message": t.get("message")}
        for t in (state.get("triaged_findings") or [])
    ]
    decisions = lg_interrupt({"pending": pending})

    # decisions: list[{rule_id, line, verdict: approve|reject|adjust, confidence}]
    if isinstance(decisions, Command) and hasattr(decisions, "resume"):
        decisions = getattr(decisions, "resume", decisions)
    if not decisions:
        return {"phase": "report"}

    rejected_keys = set()
    adjusted: dict = {}
    for d in decisions or []:
        if not isinstance(d, dict):
            continue
        key = f"{d.get('rule_id')}@{d.get('line')}"
        if d.get("verdict") == "reject":
            rejected_keys.add(key)
        elif d.get("verdict") in ("approve", "adjust") and d.get("confidence") is not None:
            adjusted[key] = float(d["confidence"])

    triaged = []
    for t in state.get("triaged_findings") or []:
        key = f"{t.get('rule_id')}@{t.get('line')}"
        if key in rejected_keys:
            continue  # 人工驳回 → 不进报告
        tr = dict(t.get("triage") or {})
        if key in adjusted:
            tr["confidence"] = adjusted[key]
            tr["rationale"] = (tr.get("rationale") or "") + "；人工复核调整"
        triaged.append({**t, "triage": tr})
    return {"triaged_findings": triaged, "phase": "report",
            "messages": [*(state.get("messages") or []), f"human_review: 驳回 {len(rejected_keys)} 条，调整 {len(adjusted)} 条"]}
