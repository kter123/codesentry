"""RetrievalAgent（§7.2）：为候选 findings 拉代码切片 + kb 条目。"""

from codesentry.rag.retrieve import hybrid_search


def _fake_vec_for(text: str, dims: int = 8) -> list[float]:
    # M3 占位：embedding tmp 合成（graph 层已有真通道时用真 vec；M3.5 接）
    seed = sum(ord(c) for c in text[:20]) % 100 / 100.0
    return [seed] * dims


def run_retrieval(state: dict) -> dict:
    findings = state.get("engine_findings") or []
    evidence: dict = {}
    from codesentry.rag.experience import search_patterns, search_vuln_cases, seed_experience
    from codesentry.rag.graphrag import ensure_graph, graph_context

    try:
        seed_experience()
    except Exception:  # noqa: BLE001, S110
        pass

    project = str(state.get("repo_path") or "")
    try:
        ensure_graph(project)
    except Exception:  # noqa: BLE001, S110
        pass

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
        query = f"{f.get('message', '')} {f.get('rule_id', '')}"
        cwe = int(f.get("cwe") or 0) or None
        evidence[key] = {
            "code": code,
            "kb": kb,
            "vuln_cases": search_vuln_cases(query, cwe=cwe, limit=3),
            "patterns": search_patterns(query, cwe=cwe, limit=3),
            "graph": graph_context(project, str(f.get("file") or ""), int(f.get("line") or 0)),
        }
    return {"evidence": evidence, "phase": "triage"}
