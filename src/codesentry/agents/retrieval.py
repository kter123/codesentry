"""RetrievalAgent（§7.2）：为候选 findings 拉代码切片 + kb 条目 + 图邻域。"""

from codesentry.rag.retrieve import hybrid_search, rerank


def run_retrieval(state: dict) -> dict:
    findings = state.get("engine_findings") or []
    evidence: dict = {}
    from codesentry.rag.embedding import embed_texts
    from codesentry.rag.experience import search_patterns, search_vuln_cases, seed_experience
    from codesentry.rag.graph_query import subgraph_for_finding

    try:
        seed_experience()
    except Exception:  # noqa: BLE001, S110
        pass

    from pathlib import Path

    project = str(Path(str(state.get("repo_path") or "")).resolve())
    queries = [
        f"{f.get('message', '')} {f.get('rule_id', '')}".strip() for f in findings
    ]
    vectors = embed_texts(queries)

    for f, vec, query in zip(findings, vectors, queries):
        key = f"{f.get('rule_id')}@{f.get('line')}"
        try:
            code = rerank(
                hybrid_search("code", query, vec, top_k=6), query,
                path=str(f.get("file") or ""),
            )[:4]
        except Exception:  # noqa: BLE001 - 无库/无向量时跳过 evidence（空证仍 triage）
            code = []
        try:
            kb = hybrid_search("kb", query, vec, top_k=3)
        except Exception:  # noqa: BLE001
            kb = []
        cwe = int(f.get("cwe") or 0) or None
        try:
            graph = subgraph_for_finding(project, f)
        except Exception:  # noqa: BLE001 - 图不可用时降级
            graph = {"nodes": [], "edges": []}
        evidence[key] = {
            "code": code,
            "kb": kb,
            "vuln_cases": search_vuln_cases(query, cwe=cwe, limit=3),
            "patterns": search_patterns(query, cwe=cwe, limit=3),
            "graph": graph,
        }
    return {"evidence": evidence, "phase": "triage"}
