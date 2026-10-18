"""kb 目录导入（agent.md FR-5：CWE/OWASP + 用户自有规范；内容全部入库 kb_chunks）。"""

from pathlib import Path

from codesentry.db import repo as db_repo

SUPPORTED_EXTS = {".md", ".txt", ".json"}


def import_kb_dir(root: str) -> int:
    """导入目录下全部 md/txt/json 文本为 kb_chunks（EmbeddingClient.from_config() 出向量）。

    调用方需先配置 embedding 通道（本地 bge-m3 或远程兼容接口，D10）。
    幂等：同 content_sha256 跳过。
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
    from codesentry.rag.embedding import EmbeddingClient

    client = EmbeddingClient.from_config()
    embeddings = client.embed([it["content"][:8000] for it in items])
    return db_repo.upsert_kb_chunks(items, embeddings)


def kb_fixture_to_items(fixture: Path) -> list[dict]:
    import json

    return json.loads(fixture.read_text())
