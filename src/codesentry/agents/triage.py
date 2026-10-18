"""TriageAgent（§7.2）：LLM 验证降噪 + 保留/降级/否决 + 修复建议。

LLM 失败标「未验证」保留引擎原始结论（§10）；vuln_cases 检索在 M3.5 接入。
"""

import json
import re

VERDICTS = ("keep", "demote", "reject")


def _parse_triage_json(text: str) -> dict | None:
    # 宽松提取首个 JSON 对象
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def triage_one(llm, finding: dict, evidence: dict, kb: list[dict] | None = None) -> dict:
    """对单个 finding 调 LLM 验证。输出 dict 含 verdict/confidence/rationale/fix_advice。"""
    import json as _json

    system = (
        "你是代码安全审计 TriageAgent。输入一个 finding 和证据切片。"
        "判断：reachable（污点可达）/ unreachable / uncertain，并给置信度 0-1 与修复建议。"
        '只输出 JSON：{"verdict": "keep|demote|reject", "confidence": 0.0-1.0,'
        ' "rationale": "一句中理由", "fix_advice": "修复建议"}'
    )
    user = _json.dumps(
        {"finding": finding, "evidence": evidence.get("code", [])[:5], "kb": (kb or [])[:3]},
        ensure_ascii=False,
    )[:12000]
    try:
        text = llm.complete(system, user, model_role="deep")
        parsed = _parse_triage_json(text)
        if parsed and parsed.get("verdict") in VERDICTS:
            return parsed
        return {"verdict": "keep", "confidence": 0.4, "rationale": "LLM 输出不可解析——按保守未验证保留",
                "fix_advice": finding.get("message", "")}
    except Exception as e:  # noqa: BLE001 - LLM 失败必须保留引擎原始结论（§10）
        return {"verdict": "keep", "confidence": 0.3, "rationale": f"未验证（LLM 失败：{str(e)[:60]}）",
                "fix_advice": ""}


def run_triage(state: dict, llm=None) -> dict:
    """节点签名：state -> update。llm 由 graph 层注入；None 时全部标未验证保留。"""
    findings = state.get("engine_findings") or []
    evd = state.get("evidence") or {}
    triaged: list[dict] = []
    for f in findings:
        if llm is None:
            t = {"verdict": "keep", "confidence": float(f.get("confidence") or 0.5),
                 "rationale": "无 LLM（M3 mock 模式）——保留", "fix_advice": ""}
        else:
            t = triage_one(llm, f, evd.get(str(f.get("rule_id")) + "@" + str(f.get("line")), {}))
        out = {**f, "triage": t}
        if t["verdict"] != "reject":
            triaged.append(out)
    phase = "poc_gen" if triaged else "report"
    return {"triaged_findings": triaged, "phase": phase}
