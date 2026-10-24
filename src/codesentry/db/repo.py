"""入库 DAO（agent.md §8；幂等靠 content_sha256）。"""

import hashlib
import json

from codesentry.db.pool import get_conn
from codesentry.rag.chunker import Chunk


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def upsert_code_chunks(project: str, chunks: list[Chunk], embeddings: list[list[float] | None]) -> int:
    """按 content_sha256 幂等写入；embedding 为 None 时走 FTS。返回新写入数。"""
    assert len(chunks) == len(embeddings)
    if not chunks:
        return 0
    digests = [sha256(c.content) for c in chunks]
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT content_sha256 FROM code_chunks WHERE project=%s AND content_sha256 = ANY(%s)",
            (project, digests),
        )
        existing = {r[0] for r in cur.fetchall()}
        rows = []
        inserted = 0
        for c, vec, h in zip(chunks, embeddings, digests):
            if h in existing:
                continue
            existing.add(h)
            rows.append((
                project, c.path, c.symbol_name, c.symbol_kind, c.start_line, c.end_line,
                c.signature, c.docstring, json.dumps(c.call_refs), c.content, c.lang, h,
                _vec_literal(vec) if vec else None,
            ))
            inserted += 1
        if rows:
            cur.executemany(
                """
                INSERT INTO code_chunks
                    (project, path, symbol_name, symbol_kind, start_line, end_line,
                     signature, docstring, call_refs, content, lang, content_sha256, embedding)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)
                """,
                rows,
            )
        conn.commit()
    return inserted


def upsert_kb_chunks(items: list[dict], embeddings: list[list[float]]) -> int:
    """items: {source,title,content,lang}；按 content_sha256 幂等。"""
    assert len(items) == len(embeddings)
    inserted = 0
    with get_conn() as conn:
        for it, vec in zip(items, embeddings):
            h = sha256(it["content"])
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM kb_chunks WHERE content_sha256 = %s", (h,))
                if cur.fetchone():
                    continue
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO kb_chunks (source, title, content, content_sha256, embedding, lang)
                    VALUES (%s,%s,%s,%s,%s::vector,%s)
                    """,
                    (it["source"], it["title"], it["content"], h, _vec_literal(vec), it.get("lang", "zh")),
                )
            inserted += 1
        conn.commit()
    return inserted


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"
