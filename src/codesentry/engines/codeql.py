"""CodeQL 引擎：仅开源代码场景（agent.md FR-3/§3）。

平台不分发 CodeQL CLI；仅探测 CODESENTRY_CODEQL_BIN。
真实现（M1.5）：codeql database create → codeql database analyze（用户自配 query pack）→ SARIF 解析。
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from codesentry.models import EngineResult, Finding

CODEQL_LANG = {
    "python": "python",
    "java": "java",
    "javascript": "javascript",
    "typescript": "javascript",
    "go": "go",
    "c": "cpp",
    "cpp": "cpp",
}


def _parse_sarif(path: Path, repo: str | None = None) -> list[Finding]:
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    from codesentry.engines.codeql_graph import normalize_sarif_uri

    out: list[Finding] = []
    for run in doc.get("runs", []):
        rules_list = run.get("tool", {}).get("driver", {}).get("rules", []) or []
        rules = {i: r.get("id", "unknown") for i, r in enumerate(rules_list)}
        rule_props = {i: (r.get("properties") or {}) for i, r in enumerate(rules_list)}
        for res in run.get("results", []):
            loc = ((res.get("locations") or [{}])[0]).get("physicalLocation", {})
            region = loc.get("region", {})
            props = res.get("properties", {}) or {}
            rule_index = res.get("ruleIndex", -1)
            rule_id = rules.get(rule_index, res.get("ruleId", "unknown"))
            rule_meta = rule_props.get(rule_index, {}) or {}
            level = res.get("level") or rule_meta.get("problem.severity") or "warning"
            severity = {"error": "high", "warning": "medium", "note": "low"}.get(
                str(level).lower(), "medium"
            )
            cwe = 610
            cwe_raw = props.get("cwe") or rule_meta.get("cwe")
            if cwe_raw is None and isinstance(res.get("rule"), dict):
                cwe_raw = res["rule"].get("properties", {}).get("cwe")
            if cwe_raw is None:
                tags = rule_meta.get("tags") or []
                if isinstance(tags, list):
                    cwe_raw = next(
                        (t for t in tags if "cwe" in str(t).lower()), None
                    )
            if isinstance(cwe_raw, list):
                cwe_raw = cwe_raw[0] if cwe_raw else None
            match = re.search(r"cwe[-_/]?(\d+)", str(cwe_raw or ""), re.IGNORECASE)
            if match:
                cwe = int(match.group(1))
            line_no = int(region.get("startLine", -1))
            if line_no < 1:
                continue
            uri = loc.get("artifactLocation", {}).get("uri", "")
            file_name = normalize_sarif_uri(uri, repo) if repo else str(uri)
            if not file_name:
                file_name = str(uri)
            out.append(
                Finding(
                    rule_id=rule_id,
                    cwe=cwe,
                    severity=severity,  # type: ignore[arg-type]
                    confidence=0.7,
                    file=file_name,
                    line=line_no,
                    message=res.get("message", {}).get("text", ""),
                    engine="codeql",
                    taint_metadata={"source": "codeql-sarif"},
                )
            )
    return out


def run_codeql(
    repo: str,
    lang: str,
    OSS: bool,
    out_dir: str,
    *,
    timeout: int | None = None,
    codeql_bin: str | None = None,
) -> EngineResult:
    # Gate 强制（调用方也应先过 LicenseGate；此处防御性再查）
    if not OSS:
        return EngineResult(
            engine="codeql", status="unavailable",
            reason="license gate: closed-source target denies CodeQL",
        )
    from codesentry.control.engine_config import resolve_codeql_config

    cfg = resolve_codeql_config(lang)
    bin_name = (codeql_bin if codeql_bin and codeql_bin != "codeql" else "")
    bin_name = bin_name or cfg.binary or "codeql"
    codeql_path = shutil.which(bin_name)
    if codeql_path is None:
        return EngineResult(engine="codeql", status="unavailable",
                            reason=f"binary not found: {bin_name}")
    db_lang = CODEQL_LANG.get(lang)
    if db_lang is None:
        return EngineResult(engine="codeql", status="unavailable", reason=f"unsupported language for CodeQL: {lang}")

    timeout_s = int(timeout or cfg.timeout_s)
    work = Path(os.environ.get("CODESENTRY_WORK_DIR", ".codesentry")) / "codeql-db"
    work.mkdir(parents=True, exist_ok=True)
    fingerprint = _repo_fingerprint(repo)
    db_path = work / f"{db_lang}-{fingerprint}"
    result_sarif = Path(out_dir) / f"codeql-{db_lang}.sarif"

    def _run(cmd, step):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=False)
        if r.returncode != 0:
            return EngineResult(engine="codeql", status="crashed",
                                reason=f"{step} exit {r.returncode}: {r.stderr[-400:]}")
        return None

    if not (cfg.cache and db_path.exists()):
        cmd = [codeql_path, "database", "create", str(db_path),
               f"--language={db_lang}", "--source-root", repo,
               f"--build-mode={cfg.build_mode}"]
        if cfg.search_path:
            cmd += ["--search-path", cfg.search_path]
        if cfg.build_mode == "manual" and cfg.build_command:
            cmd += ["--command", cfg.build_command]
        if not cfg.cache:
            cmd.append("--overwrite")
        err = _run(cmd, "db create")
        if err:
            return err
    analyze = [codeql_path, "database", "analyze", str(db_path),
               "--format=sarif-latest", "--output", str(result_sarif)]
    if cfg.search_path:
        analyze += ["--search-path", cfg.search_path]
    analyze.append(cfg.suite)
    err = _run(analyze, "analyze")
    if err:
        return err
    findings = _parse_sarif(result_sarif, repo)
    return EngineResult(engine="codeql", status="ok", findings=findings,
                        lang=db_lang, artifact=str(result_sarif))


def _repo_fingerprint(repo: str) -> str:
    import hashlib

    h = hashlib.sha256()
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "target", "build", "dist")]
        for name in sorted(files):
            path = Path(root) / name
            try:
                stat = path.stat()
            except OSError:
                continue
            h.update(str(path.relative_to(repo)).encode())
            h.update(str(int(stat.st_mtime_ns)).encode())
            h.update(str(stat.st_size).encode())
    return h.hexdigest()[:16]
