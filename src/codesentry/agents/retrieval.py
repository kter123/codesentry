"""RetrievalAgent（§7.2）：为候选 findings 拉代码切片 + kb 条目。"""

from codesentry.rag.retrieve import hybrid_search


def _fake_vec_for(text: str, dims: int = 8) -> list[float]:
    # M3 占位：embedding tmp 合成（graph 层已有真通道时用真 vec；M3.5 接）
    seed = sum(ord(c) for c in text[:20]) % 100 / 100.0
    return [seed] * dims


def run_retrieval(state: dict) -> dict:
    findings = state.get("engine_findings") or []
    evidence: dict = {}
    for f in findings:
        key = f"{f.get('rule_id')}@{f.get('line')}"
        code = []
        kb = []
        try:
            code = hybrid_search("code", f.get("message", ""), _fake_vec_for(f.get("rule_id", "")), top_k=4)
        except Exception:  # noqa: BLE001 - 无库/无向量时跳过 evidence（空证仍 triage）
            code = []
        try:
            kb = hybrid_search("kb", f.get("message", ""), _fake_vec_for(f.get("rule_id", "")), top_k=3)
        except Exception:  # noqa: BLE001
            kb = []
        evidence[key] = {"code": code, "kb": kb}
    return {"evidence": evidence, "phase": "triage"}
