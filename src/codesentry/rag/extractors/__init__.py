"""语言抽取器注册与统一入口。"""

from __future__ import annotations

from codesentry.rag.extractors.base import (
    CodeEdge,
    CodeNode,
    ExtractResult,
    endpoint_key,
    file_key,
    node_key,
    normalize_route,
    register,
)
from codesentry.rag.extractors.generic import extractor_for
from codesentry.rag.extractors.java import JavaExtractor
from codesentry.rag.extractors.python import PythonExtractor

register(PythonExtractor())
register(JavaExtractor())
for _lang in ("javascript", "typescript", "tsx", "go", "php", "c", "cpp"):
    _extractor = extractor_for(_lang)
    if _extractor is not None:
        register(_extractor)

EXT_TO_LANG = {
    ".py": "python",
    ".java": "java",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
}


def lang_for_path(path: str) -> str | None:
    suffix = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return EXT_TO_LANG.get(suffix)


def extract(path: str, lang: str, source: str) -> ExtractResult:
    from codesentry.rag.extractors.base import get_extractor

    extractor = get_extractor(lang)
    if extractor is None:
        return ExtractResult()
    return extractor.extract(path, source)


__all__ = [
    "CodeEdge", "CodeNode", "ExtractResult", "endpoint_key", "extract", "file_key",
    "lang_for_path", "node_key", "normalize_route",
]
