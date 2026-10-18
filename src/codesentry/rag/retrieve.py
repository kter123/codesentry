"""混合检索（agent.md FR-5）：pgvector 向量 <=> + tsvector 全文，score 归一 0–1。"""

from typing import Any

from codesentry.db.pool import get_conn

W_VEC = 0.6
W_FTS = 0.4

_COLLECTION_TO_TABLE = {"code": "code_chunks", "kb": "kb_chunks"}


def hybrid_search(
    collection: str,
    query_text: str,
    query_vec: list[float],
    top_k: int = 8,
) -> list[dict[str, Any]]:
    table = _COLLECTION_TO_TABLE[collection]
    assert table in _COLLECTION_TO_TABLE.values()
    vec_literal = "[" + ",".join(f"{x:.8f}" for x in query_vec) + "]"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    {"symbol_name, symbol_kind, path, start_line, end_line, signature, content"
                     if table == "code_chunks" else "title, source, content"} AS head,
                    (
                        {W_VEC} * (1 - (embedding <=> %s::vector))
                        + {W_FTS} * CASE WHEN to_tsvector('simple', content) @@ plainto_tsquery('simple', %s)
                            THEN 1.0 ELSE 0.0 END
                    ) AS score
                FROM {table}
                WHERE embedding IS NOT NULL OR to_tsvector('simple', content) IS NOT NULL
                ORDER BY score DESC
                LIMIT %s
                """,
                (vec_literal, query_text, top_k),
            )
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return [
        {**r, "score": float(r["score"])} for r in rows if r["score"] > 0
    ]
