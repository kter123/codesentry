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


def list_chunks(source: str = "", limit: int = 50) -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            if source:
                cur.execute(
                    "SELECT id, source, title, content,"
                    " CASE WHEN embedding IS NULL THEN 0 ELSE vector_dims(embedding) END"
                    " FROM kb_chunks WHERE source=%s ORDER BY id LIMIT %s",
                    (source, max(1, min(int(limit), 200))),
                )
            else:
                cur.execute(
                    "SELECT id, source, title, content,"
                    " CASE WHEN embedding IS NULL THEN 0 ELSE vector_dims(embedding) END"
                    " FROM kb_chunks ORDER BY id DESC LIMIT %s",
                    (max(1, min(int(limit), 200)),),
                )
            rows = cur.fetchall()
        return [{"id": r[0], "source": r[1], "title": r[2], "content": r[3],
                 "embedding_dims": int(r[4] or 0)} for r in rows]
    except Exception:  # noqa: BLE001
        return []


def preview_chunks(content: str, size: int = 800) -> list[dict]:
    """按段落聚合到近似 size 字符，返回切块预览（不写库）。"""
    paragraphs = [p.strip() for p in str(content).split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if current and len(current) + len(para) + 2 > size:
            chunks.append(current)
            current = para
        elif current:
            current += "\n\n" + para
        else:
            current = para
    if current:
        chunks.append(current)
    return [{"index": i + 1, "chars": len(c), "content": c} for i, c in enumerate(chunks[:200])]


def rebuild(source: str = "") -> dict:
    """为缺失/错误维度的 chunk 重新计算 embedding；source 为空时全量。"""
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn
        from codesentry.rag.embedding import embed_texts

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            if source:
                cur.execute(
                    "SELECT id, content FROM kb_chunks WHERE source=%s AND embedding IS NULL",
                    (source,),
                )
            else:
                cur.execute("SELECT id, content FROM kb_chunks WHERE embedding IS NULL")
            rows = cur.fetchall()
        if not rows:
            return {"ok": True, "rebuilt": 0, "degraded": False}
        vectors = embed_texts([r[1] for r in rows])
        updated = 0
        with get_conn() as conn, conn.cursor() as cur:
            for (chunk_id, _content), vec in zip(rows, vectors):
                if not vec:
                    continue
                cur.execute(
                    "UPDATE kb_chunks SET embedding=%s::vector WHERE id=%s",
                    (_vec(vec), chunk_id),
                )
                updated += 1
            conn.commit()
        return {"ok": True, "rebuilt": updated, "degraded": any(v is None for v in vectors)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "rebuilt": 0, "degraded": True, "error": str(exc)[:200]}


def delete_source(source: str) -> int:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM kb_chunks WHERE source=%s", (source,))
            deleted = cur.rowcount
            conn.commit()
        return int(deleted)
    except Exception:  # noqa: BLE001
        return 0


def _vec(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


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
