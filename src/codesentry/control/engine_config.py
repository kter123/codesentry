"""引擎配置解析：DB app_settings → env → 本机默认位置。"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

SUITE_NAMES = {
    "java": "java",
    "python": "python",
    "javascript": "javascript",
    "typescript": "javascript",
    "go": "go",
    "c": "cpp",
    "cpp": "cpp",
    "csharp": "csharp",
    "ruby": "ruby",
}


@dataclass
class CodeQLConfig:
    binary: str
    search_path: str
    suite: str
    build_mode: str
    build_command: str
    timeout_s: int
    cache: bool


def _setting(key: str) -> str:
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT value FROM app_settings WHERE key=%s", (key,))
            row = cur.fetchone()
        return str(row[0]) if row else ""
    except Exception:  # noqa: BLE001
        return ""


def _home_defaults() -> tuple[str, str]:
    binary = str(Path.home() / ".codesentry" / "tools" / "codeql" / "codeql")
    packs = str(Path.home() / ".codeql" / "packages")
    return binary, packs


def resolve_codeql_config(lang: str) -> CodeQLConfig:
    from codesentry.config import get_settings

    s = get_settings()
    binary = (_setting("codeql_bin") or os.environ.get("CODESENTRY_CODEQL_BIN")
              or shutil.which("codeql") or "")
    home_bin, home_packs = _home_defaults()
    if not binary and Path(home_bin).is_file():
        binary = home_bin

    search_path = (_setting("codeql_search_path")
                   or os.environ.get("CODESENTRY_CODEQL_SEARCH_PATH") or "")
    if not search_path and Path(home_packs).is_dir():
        search_path = home_packs

    suite_lang = SUITE_NAMES.get(lang, lang)
    suite = (_setting("codeql_suite") or os.environ.get("CODESENTRY_QUERY_PACK")
             or s.codeql_suite or "")
    if suite:
        suite = suite.replace("{lang}", suite_lang)
    else:
        suite = (f"codeql/{suite_lang}-queries:"
                 f"codeql-suites/{suite_lang}-security-extended.qls")

    build_mode = (_setting("codeql_build_mode") or os.environ.get("CODESENTRY_CODEQL_BUILD_MODE")
                  or s.codeql_build_mode or "none")
    if build_mode not in ("none", "autobuild", "manual"):
        build_mode = "none"
    command = (_setting("codeql_build_command")
               or os.environ.get("CODESENTRY_BUILD_COMMAND") or s.codeql_build_command or "")
    if build_mode == "manual" and not command:
        build_mode = "none"

    try:
        timeout_s = int(_setting("codeql_timeout_s") or s.codeql_timeout_s or 1800)
    except ValueError:
        timeout_s = 1800
    cache_raw = _setting("codeql_db_cache")
    cache = s.codeql_db_cache if cache_raw == "" else cache_raw.lower() not in ("0", "false", "no")

    return CodeQLConfig(
        binary=binary, search_path=search_path, suite=suite,
        build_mode=build_mode, build_command=command,
        timeout_s=max(60, timeout_s), cache=cache,
    )


def codeql_status(lang: str = "java") -> dict:
    cfg = resolve_codeql_config(lang)
    binary = shutil.which(cfg.binary) if cfg.binary else None
    version = ""
    languages: list[str] = []
    packs: list[str] = []
    error = ""
    if binary:
        try:
            proc = subprocess.run([binary, "version"], capture_output=True, text=True,
                                  timeout=10, check=False)
            if proc.returncode == 0:
                version = (proc.stdout or proc.stderr).splitlines()[0][:160]
            proc = subprocess.run([binary, "resolve", "languages"], capture_output=True,
                                  text=True, timeout=10, check=False)
            if proc.returncode == 0:
                for line in (proc.stdout or "").splitlines():
                    name = line.split(" (")[0].strip()
                    if name:
                        languages.append(name)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)[:200]
    try:
        if cfg.search_path and Path(cfg.search_path).is_dir():
            base = Path(cfg.search_path) / "codeql"
            root = base if base.is_dir() else Path(cfg.search_path)
            packs = sorted(p.name for p in root.iterdir() if p.is_dir())[:30]
    except OSError:
        pass
    return {"found": bool(binary), "binary": binary or cfg.binary,
            "version": version, "search_path": cfg.search_path,
            "suite": cfg.suite, "build_mode": cfg.build_mode,
            "languages": languages, "packs": packs, "error": error}
