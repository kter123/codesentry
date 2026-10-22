"""知识库运营（M6.7/FR-35）：统计、文本检索、手工导入。"""

from __future__ import annotations

import hashlib


def stats() -> dict:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*), count(DISTINCT source) FROM kb_chunks")
            chunks, sources = cur.fetchone()
            cur.execute("SELECT source, count(*) FROM kb_chunks GROUP BY source ORDER BY 2 DESC LIMIT 20")
            rows = cur.fetchall()
        return {"chunks": int(chunks), "sources": int(sources),
                "by_source": [{"source": r[0], "chunks": r[1]} for r in rows]}
    except Exception:  # noqa: BLE001
        return {"chunks": 0, "sources": 0, "by_source": []}


def search(query: str, top_k: int = 5) -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, source, title, content,"
                " ts_rank(to_tsvector('simple', content), plainto_tsquery('simple', %s)) AS score"
                " FROM kb_chunks WHERE to_tsvector('simple', content) @@ plainto_tsquery('simple', %s)"
                " ORDER BY score DESC LIMIT %s",
                (query[:500], query[:500], max(1, min(int(top_k), 20))),
            )
            rows = cur.fetchall()
        return [{"id": r[0], "source": r[1], "title": r[2], "content": r[3][:800],
                 "score": float(r[4] or 0)} for r in rows]
    except Exception:  # noqa: BLE001
        return []


def import_text(source: str, title: str, content: str, lang: str = "zh") -> bool:
    """按段落切块写入（无 embedding，后续可重建索引）。"""
    if not content.strip():
        return False
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        chunks = [p.strip() for p in content.split("\n\n") if p.strip()][:200]
        with get_conn() as conn, conn.cursor() as cur:
            for i, chunk in enumerate(chunks):
                h = hashlib.sha256(chunk.encode()).hexdigest()
                cur.execute(
                    "SELECT 1 FROM kb_chunks WHERE content_sha256=%s AND source=%s", (h, source)
                )
                if cur.fetchone():
                    continue
                cur.execute(
                    "INSERT INTO kb_chunks (source, title, content, content_sha256, lang)"
                    " VALUES (%s,%s,%s,%s,%s)",
                    (source, f"{title}#{i + 1}", chunk, h, lang),
                )
            conn.commit()
        return True
    except Exception:  # noqa: BLE001
        return False
