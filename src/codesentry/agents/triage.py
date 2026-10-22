"""TriageAgent（§7.2）：LLM 验证降噪 + 保留/降级/否决 + 修复建议。

M6.1：支持 AgentRuntime 注入（生效 Prompt + Skills + 绑定 LLM）；无 LLM 时保留引擎原始结论。
"""

import json
import re
from typing import Any

VERDICTS = ("keep", "demote", "reject")

_DEFAULT_SYSTEM = (
    "你是代码安全审计 TriageAgent。输入一个 finding 和证据切片。"
    "判断：reachable（污点可达）/ unreachable / uncertain，并给置信度 0-1 与修复建议。"
    "如需更多证据，可输出 {\"tool_calls\": [{\"tool\": \"read_source\", \"args\": {\"path\": \"a.py\", \"start\": 1, \"end\": 80}}]}；"
    "可用工具：read_source、search_code、read_evidence。获得足够证据后输出最终 JSON。"
    '只输出 JSON：{"verdict": "keep|demote|reject", "confidence": 0.0-1.0,'
    ' "rationale": "一句中理由", "fix_advice": "修复建议"}'
)


def _parse_triage_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def triage_one(llm, finding: dict, evidence: dict, kb: list[dict] | None = None,
               system: str | None = None, tools=None, max_iterations: int = 8) -> dict:
    """对单个 finding 调 LLM 验证。输出 dict 含 verdict/confidence/rationale/fix_advice。"""
    user = json.dumps(
        {
            "finding": finding,
            "evidence": evidence.get("code", [])[:5],
            "kb": (kb or [])[:3],
            "vuln_cases": (evidence.get("vuln_cases") or [])[:3],
            "patterns": (evidence.get("patterns") or [])[:3],
            "graph": evidence.get("graph") or {},
        },
        ensure_ascii=False,
    )[:12000]
    if system and "verdict" not in system:
        system = system.rstrip() + "\n\n" + _DEFAULT_SYSTEM
    system = system or _DEFAULT_SYSTEM
    try:
        if tools:
            from codesentry.agents.tools import run_tool_loop

            text, trace = run_tool_loop(
                llm, system, user, tools=tools, max_iterations=max_iterations, model_role="deep"
            )
        else:
            text = llm.complete(system, user, model_role="deep")
            trace = []
        parsed = _parse_triage_json(text)
        if parsed and parsed.get("verdict") in VERDICTS:
            parsed["tool_trace"] = trace
            return parsed
        return {"verdict": "keep", "confidence": 0.4,
                "rationale": "LLM 输出不可解析——按保守未验证保留",
                "fix_advice": finding.get("message", ""), "tool_trace": trace}
    except Exception as e:  # noqa: BLE001 - LLM 失败必须保留引擎原始结论（§10）
        return {"verdict": "keep", "confidence": 0.3,
                "rationale": f"未验证（LLM 失败：{str(e)[:60]}）", "fix_advice": ""}


def _merge_messages(state: dict, runtime) -> list:
    existing = list(state.get("messages") or [])
    if runtime is not None:
        existing.extend(f"{runtime.agent}: {w}" for w in runtime.warnings)
    return existing


def run_triage(state: Any, llm=None, runtime=None) -> dict:
    """节点签名：state -> update。runtime 提供生效 Prompt/Skills/LLM。"""
    findings = state.get("engine_findings") or []
    evd = state.get("evidence") or {}
    messages = _merge_messages(state, runtime)

    from codesentry.config import get_settings

    max_findings = get_settings().max_findings
    if len(findings) > max_findings:
        messages.append(f"triage: findings 截断 {len(findings)}→{max_findings}")
        findings = findings[:max_findings]

    if runtime is not None and not runtime.enabled:
        passthrough = []
        for f in findings:
            t = {"verdict": "keep", "confidence": float(f.get("confidence") or 0.5),
                 "rationale": "agent disabled——保留引擎原始结论", "fix_advice": ""}
            passthrough.append({**f, "triage": t})
        return {
            "triaged_findings": passthrough,
            "phase": "poc_gen" if passthrough else "report",
            "messages": messages,
            **_snapshot_updates(state, runtime),
        }

    if runtime is not None:
        llm = runtime.llm or llm
    system = runtime.system() if runtime is not None else None

    triaged: list[dict] = []
    try:
        from codesentry.agents.confidence import calibrate, compute, evidence_score
        from codesentry.control.calibration import get_params

        calib = get_params()
    except Exception:  # noqa: BLE001
        calibrate = compute = evidence_score = None  # type: ignore[assignment]
        calib = {"a": 1.0, "b": 0.0}
    try:
        from codesentry.agents.tools import build_tools

        tools = build_tools(state)
    except Exception:  # noqa: BLE001
        tools = {}
    max_iterations = int(getattr(runtime, "max_iterations", 8) or 8)
    for f in findings:
        key = str(f.get("rule_id")) + "@" + str(f.get("line"))
        if llm is None:
            t = {"verdict": "keep", "confidence": float(f.get("confidence") or 0.5),
                 "rationale": "无 LLM（M3 mock 模式）——保留", "fix_advice": ""}
        else:
            t = triage_one(
                llm, f, evd.get(key, {}), system=system,
                tools=tools, max_iterations=max_iterations,
            )
        if compute is not None and evidence_score is not None and calibrate is not None:
            ev = evidence_score(evd.get(key, {}), has_chain=bool(evd.get(key, {}).get("taint_chain")))
            raw_val = t.get("confidence")
            raw = float(raw_val) if isinstance(raw_val, (int, float, str)) else 0.5
            parts = compute(
                raw, ev, calibrate(raw, calib["a"], calib["b"]),
                str(t.get("verdict") or "keep"), calibrated_params=calib,
            )
            t["confidence_parts"] = parts
            t["confidence"] = parts["final"]
        out = {**f, "triage": t, "confidence_parts": t.get("confidence_parts", {})}
        if t["verdict"] != "reject":
            triaged.append(out)
    phase = "poc_gen" if triaged else "report"
    return {
        "triaged_findings": triaged,
        "phase": phase,
        "messages": messages,
        **_snapshot_updates(state, runtime),
    }


def _snapshot_updates(state: dict, runtime) -> dict:
    if runtime is None:
        return {}
    out: dict = {}
    pv = {**(state.get("prompt_versions") or {}), **runtime.prompt_snapshot()}
    if pv:
        out["prompt_versions"] = pv
    ss = {**(state.get("skills_snapshot") or {}), **runtime.skills_snapshot()}
    if ss:
        out["skills_snapshot"] = ss
    return out
