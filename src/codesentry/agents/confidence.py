"""LLM 置信度四层模型（M6.4）：raw / evidence / calibrated / verdict-gated。"""

from __future__ import annotations

import math


def _clamp(p: float) -> float:
    return max(1e-6, min(1 - 1e-6, float(p)))


def logit(p: float) -> float:
    p = _clamp(p)
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def calibrate(raw: float, a: float = 1.0, b: float = 0.0) -> float:
    return sigmoid(a * logit(raw) + b)


def evidence_score(evidence: dict | None, *, has_chain: bool = False) -> float:
    evidence = evidence or {}
    code = evidence.get("code") or []
    kb = evidence.get("kb") or []
    if not code and not kb:
        return 0.3  # 仅断言，降权
    score = 0.5 + min(0.3, 0.08 * len(code)) + min(0.1, 0.03 * len(kb))
    if has_chain or evidence.get("taint_chain"):
        score += 0.2
    return round(min(1.0, score), 4)


def compute(
    raw: float,
    evidence: float,
    calibrated: float,
    verdict: str,
    *,
    calibrated_params: dict | None = None,
) -> dict:
    raw = _clamp(raw)
    evidence = _clamp(evidence)
    calibrated = _clamp(calibrated)
    final = min(raw, evidence, calibrated)
    if verdict == "reject":
        gated = 0.1
    elif verdict == "demote":
        gated = round(final * 0.7, 4)
    else:
        gated = final
    return {
        "raw": round(raw, 4),
        "evidence": round(evidence, 4),
        "calibrated": round(calibrated, 4),
        "verdict_gated": round(gated, 4),
        "final": round(gated, 4),
        "verdict": verdict,
        "params": calibrated_params or {},
    }
