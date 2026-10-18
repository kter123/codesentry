"""scan 主流程编排（agent.md FR-1/D8：极简 recon → Gate → 并行引擎 → 报告）。

M1 不引入 LangGraph（M3 职责）；M1 用 ThreadPoolExecutor 做引擎级并行。
"""

import concurrent.futures
import os
import shutil
from pathlib import Path

from codesentry.models import EngineResult, LicenseDeclaration, ScanProfile

ENGINE_ORDER = ["codeql", "joern", "semgrep"]

# 语言 → 文件扩展名（极简 recon）
LANG_EXTS = {
    "python": {".py"},
    "java": {".java"},
    "javascript": {".js", ".mjs", ".cjs"},
    "typescript": {".ts", ".tsx"},
    "go": {".go"},
    "c": {".c", ".h"},
    "cpp": {".cc", ".cpp", ".hpp", ".cxx"},
    "php": {".php"},
}


def select_engines(OSS: bool, lang: str | None = None) -> list[str]:
    """引擎组合（agent.md D8 + §4.2）：开源 CodeQL+Semgrep；闭源 Joern+Semgrep；PHP 无 CodeQL。"""
    if lang == "php":
        return ["joern", "semgrep"]
    if OSS:
        return ["codeql", "semgrep"]
    return ["joern", "semgrep"]


def detect_languages(repo: str) -> list[str]:
    """极简 recon：按扩展名推断语言出现（M3 ReconAgent 深化）。"""
    repo_path = Path(repo)
    found: set[str] = set()
    for root, _dirs, files in os.walk(repo_path):
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            for lang, exts in LANG_EXTS.items():
                if ext in exts:
                    found.add(lang)
    return sorted(found) if found else []


def run_engines_parallel(specs: list, **kwargs) -> list[EngineResult]:
    """并行执行引擎 callable；单个崩溃/超时捕获为降级 EngineResult（§10）。"""
    results: list[EngineResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(specs))) as pool:
        futures = {pool.submit(spec, **kwargs): spec for spec in specs}
        for fut in concurrent.futures.as_completed(futures):
            spec = futures[fut]
            try:
                results.append(fut.result())
            except Exception as e:  # noqa: BLE001 - 引擎故障必须降级不阻塞整条流水线
                name = getattr(spec, "__name__", "unknown")
                engine = next(
                    (n for n in ENGINE_ORDER if n in name), "joern"
                )
                results.append(
                    EngineResult(engine=engine, status="crashed", reason=str(e))
                )
    order = {n: i for i, n in enumerate(ENGINE_ORDER)}
    results.sort(key=lambda r: order.get(r.engine, 99))
    return results
