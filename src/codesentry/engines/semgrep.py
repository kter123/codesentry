"""Semgrep 引擎：--json 规则扫（agent.md §4.1 全场景快扫）。"""

import json

from codesentry.engines.base import run_subprocess
from codesentry.engines.normalize import normalize_semgrep
from codesentry.models import EngineResult, Finding


def run_semgrep(
    repo: str,
    *,
    config: str | None = None,
    timeout: int = 1800,
    cwd: str | None = None,
    semgrep_bin: str = "semgrep",
) -> EngineResult:
    cmd = [semgrep_bin, "scan", "--json", "--quiet", repo]
    if config:
        cmd = [semgrep_bin, "scan", "--json", "--quiet", "--config", config, repo]
    r = run_subprocess(cmd, timeout=timeout, cwd=cwd)
    if not r.ok:
        return EngineResult(engine="semgrep", status="crashed", reason=r.reason, stderr=r.stderr)
    try:
        doc = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        return EngineResult(engine="semgrep", status="crashed", reason=f"json parse: {e}")
    findings: list[Finding] = normalize_semgrep(doc)
    return EngineResult(engine="semgrep", status="ok", findings=findings)
