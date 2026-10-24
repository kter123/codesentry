"""代码切片索引：把图节点对应源码写入 code_chunks，供混合检索使用。"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from codesentry.rag.chunker import Chunk
from codesentry.rag.extractors import extract, lang_for_path
from codesentry.rag.graph_build import MAX_FILE_BYTES, SKIP_DIRS


def index_repo(
    repo_path: str,
    *,
    project: str | None = None,
    files: list[str] | None = None,
    max_chunks: int = 20000,
) -> dict:
    from codesentry.control.bootstrap import ensure_control_schema

    ensure_control_schema()
    repo = Path(repo_path).resolve()
    project = project or str(repo)
    targets = files if files is not None else _walk(repo)
    items: list[Chunk] = []
    seen: set[str] = set()
    for rel in targets:
        lang = lang_for_path(rel)
        if not lang:
            continue
        full = repo / rel
        try:
            if full.stat().st_size > MAX_FILE_BYTES:
                continue
            source = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            result = extract(rel, lang, source)
        except Exception:  # noqa: BLE001, S112 - 单文件解析失败不阻塞索引
            continue
        lines = source.splitlines()
        for node in result.nodes:
            if node.kind not in ("function", "method", "class"):
                continue
            start = max(1, node.start_line)
            end = min(len(lines), node.end_line)
            if end < start:
                continue
            content = "\n".join(lines[start - 1 : end]).strip()
            if len(content) < 30:
                continue
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            items.append(Chunk(
                path=rel, lang=lang, symbol_name=node.qualified_name or node.name,
                symbol_kind="class" if node.kind == "class" else "function",
                start_line=start, end_line=end,
                signature=(node.qualified_name or node.name)[:300],
                docstring="",
                call_refs=[c.get("name", "") for c in (node.attrs or {}).get("calls") or []],
                content=content,
            ))
            if len(items) >= max_chunks:
                break
        if len(items) >= max_chunks:
            break

    if not items:
        return {"project": project, "chunks": 0, "embedded": 0, "degraded": False}

    vectors, degraded = _embed([c.content for c in items])
    from codesentry.db.repo import upsert_code_chunks

    written = upsert_code_chunks(project, items, vectors)
    return {
        "project": project, "chunks": len(items), "written": written,
        "embedded": len(vectors), "degraded": degraded,
    }


def _walk(repo: Path) -> list[str]:
    out: list[str] = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".git")]
        for name in files:
            rel = str((Path(root) / name).relative_to(repo))
            if lang_for_path(rel):
                out.append(rel)
    return sorted(out)


def _embed(texts: list[str]) -> tuple[list[list[float] | None], bool]:
    """返回与 texts 等长的向量；不可用时置 None 并降级为 FTS。"""
    try:
        from codesentry.rag.embedding import EmbeddingClient

        client = EmbeddingClient.from_config()
        out: list[list[float] | None] = []
        for i in range(0, len(texts), 64):
            out.extend(client.embed(texts[i : i + 64]))
        if len(out) != len(texts):
            return [None] * len(texts), True
        return out, False
    except Exception:  # noqa: BLE001 - 未配置 embedding 时走 FTS
        return [None] * len(texts), True
