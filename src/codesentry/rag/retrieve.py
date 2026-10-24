"""混合检索（agent.md FR-5）：pgvector 向量 <=> + tsvector 全文，score 归一 0–1。"""

from typing import Any

from codesentry.db.pool import get_conn

W_VEC = 0.6
W_FTS = 0.4

_COLLECTION_TO_TABLE = {"code": "code_chunks", "kb": "kb_chunks"}


def hybrid_search(
    collection: str,
    query_text: str,
    query_vec: list[float] | None,
    top_k: int = 8,
) -> list[dict[str, Any]]:
    table = _COLLECTION_TO_TABLE[collection]
    assert table in _COLLECTION_TO_TABLE.values()
    if query_vec:
        vec_literal = "[" + ",".join(f"{x:.8f}" for x in query_vec) + "]"
        score = (
            f"({W_VEC} * CASE WHEN vector_dims(embedding) = %s"
            f" THEN coalesce(1 - (embedding <=> %s::vector), 0) ELSE 0 END"
            f" + {W_FTS} * CASE WHEN to_tsvector('simple', content)"
            " @@ plainto_tsquery('simple', %s) THEN 1.0 ELSE 0.0 END)"
        )
        where = ("(embedding IS NOT NULL AND vector_dims(embedding) = %s)"
                 " OR to_tsvector('simple', content) IS NOT NULL")
        params: tuple = (len(query_vec), vec_literal, query_text, len(query_vec), top_k)
    else:
        score = (
            f"{W_FTS} * CASE WHEN to_tsvector('simple', content)"
            " @@ plainto_tsquery('simple', %s) THEN 1.0 ELSE 0.0 END"
        )
        where = "to_tsvector('simple', content) IS NOT NULL"
        params = (query_text, top_k)
    with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    {"symbol_name, symbol_kind, path, start_line, end_line, signature, content"
                     if table == "code_chunks" else "title, source, content"} AS head,
                    {score} AS score
                FROM {table}
                WHERE {where}
                ORDER BY score DESC
                LIMIT %s
                """,
                params,
            )
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return [
        {**r, "score": float(r["score"] or 0)} for r in rows if (r["score"] or 0) > 0
    ]


def rerank(rows: list[dict[str, Any]], query_text: str, *, path: str = "",
           symbol: str = "") -> list[dict[str, Any]]:
    """轻量重排：同文件、符号命中、查询词命中分别加权，不引入额外模型。"""
    terms = [t for t in str(query_text).lower().split() if len(t) >= 3][:8]
    out = []
    for row in rows:
        score = float(row.get("score") or 0.0)
        row_path = str(row.get("path") or "")
        row_symbol = str(row.get("symbol_name") or "")
        if path and row_path == path:
            score += 0.15
        if symbol and symbol == row_symbol:
            score += 0.2
        content = str(row.get("content") or "").lower()
        hits = sum(1 for term in terms if term in content)
        score += min(0.1, 0.02 * hits)
        out.append({**row, "score": round(min(1.0, score), 6)})
    return sorted(out, key=lambda r: float(r["score"]), reverse=True)
