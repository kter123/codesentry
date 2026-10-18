"""CodeQL 引擎：仅开源代码场景（agent.md FR-3/§3）。

平台不分发 CodeQL CLI；仅探测 CODESENTRY_CODEQL_BIN。
"""

import os
import shutil

from codesentry.models import EngineResult

# 语言 → CodeQL 数据库语言名（§4.2；PHP 不支持）
CODEQL_LANG = {
    "python": "python",
    "java": "java",
    "javascript": "javascript",
    "typescript": "javascript",
    "go": "go",
    "c": "cpp",
    "cpp": "cpp",
}


def run_codeql(
    repo: str,
    lang: str,
    OSS: bool,
    out_dir: str,
    *,
    timeout: int = 3600,
    codeql_bin: str | None = None,
) -> EngineResult:
    # Gate 强制（调用方也应先过 LicenseGate；此处防御性再查）
    if not OSS:
        return EngineResult(
            engine="codeql", status="unavailable",
            reason="license gate: closed-source target denies CodeQL",
        )
    bin_name = codeql_bin or os.environ.get("CODESENTRY_CODEQL_BIN", "codeql")
    if shutil.which(bin_name) is None:
        return EngineResult(engine="codeql", status="unavailable", reason=f"binary not found: {bin_name}")
    db_lang = CODEQL_LANG.get(lang)
    if db_lang is None:
        return EngineResult(engine="codeql", status="unavailable", reason=f"unsupported language for CodeQL: {lang}")
    return EngineResult(engine="codeql", status="ok", reason=f"codeql probe ok: lang={db_lang}")
