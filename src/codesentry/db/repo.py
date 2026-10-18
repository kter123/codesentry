"""入库 DAO（agent.md §8；幂等靠 content_sha256）。"""

import hashlib
import json

from codesentry.db.pool import get_conn
from codesentry.rag.chunker import Chunk


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def upsert_code_chunks(project: str, chunks: list[Chunk], embeddings: list[list[float]]) -> int:
    """按 content_sha256 幂等写入；每个 chunk 必须带同维 embedding。返回新写入数。"""
    assert len(chunks) == len(embeddings)
    inserted = 0
    with get_conn() as conn:
        for c, vec in zip(chunks, embeddings):
            h = sha256(c.content)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM code_chunks WHERE content_sha256 = %s AND project = %s",
                    (h, project),
                )
                if cur.fetchone():
                    continue
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO code_chunks
                        (project, path, symbol_name, symbol_kind, start_line, end_line,
                         signature, docstring, call_refs, content, lang, content_sha256, embedding)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)
                    """,
                    (
                        project, c.path, c.symbol_name, c.symbol_kind,
                        c.start_line, c.end_line, c.signature, c.docstring,
                        json.dumps(c.call_refs), c.content, c.lang, h,
                        _vec_literal(vec),
                    ),
                )
                inserted += 1
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
