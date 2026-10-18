"""kb 目录导入（agent.md FR-5：CWE/OWASP + 用户自有规范；内容全部入库 kb_chunks）。"""

import json
from pathlib import Path

from codesentry.db import repo as db_repo

SUPPORTED_EXTS = {".md", ".txt", ".json"}


def import_kb_dir(root: str, *, embed: bool = False) -> int:
    """导入目录下全部 md/txt/json 文本为 kb_chunks。

    embed=False 时只占位向量空（M2 允许无向量检索纯全文；embedding 由调用方批量补）。
    阻塞红线：对本目录内容不限制来源——kb 内容由用户提供（agent.md §3）。
    """
    items: list[dict] = []
    src = Path(root)
    if not src.is_dir():
        raise FileNotFoundError(f"kb 目录不存在：{root}")
    for p in sorted(src.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in SUPPORTED_EXTS:
            continue
        content = p.read_text(encoding="utf-8", errors="replace").strip()
        if not content:
            continue
        items.append({"source": str(p), "title": p.stem, "content": content, "lang": "zh"})
    if not items:
        return 0
    embeddings = [[0.0] for _ in items] if not embed else None
    if embeddings is None:
        from codesentry.rag.embedding import EmbeddingClient

        client = EmbeddingClient.from_config()
        embeddings = client.embed([it["content"][:8000] for it in items])
    return db_repo.upsert_kb_chunks(items, embeddings)


def kb_fixture_to_items(fixture: Path) -> list[dict]:
    return json.loads(fixture.read_text())
