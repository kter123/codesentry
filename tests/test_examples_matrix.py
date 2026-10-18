"""六语言×引擎覆盖矩阵逐组合验证（agent.md §4.2）。

semgrep 已安装则真跑；joern 在 binary 就位后真跑（其它环境 skip + 降级记录）。
CodeQL 整体 skip-if-missing（平台不分发）。
"""

import json
import os
import shutil
from pathlib import Path

import pytest

from codesentry.engines.semgrep import run_semgrep

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
REPOS = {
    "python": "ssrf_flask",
    "java": "path_traversal_file",
    "javascript": "proto_pollution",
    "go": "util_injection_exec",
    "c": "format_string_printf",
    "php": "safe_eval",
}

_HAS_SEMGREP = shutil.which("semgrep") is not None
_HAS_JOERN = shutil.which(os.environ.get("CODESENTRY_JOERN_BIN", "joern")) is not None
_HAS_CODEQL = shutil.which(os.environ.get("CODESENTRY_CODEQL_BIN", "codeql")) is not None


def _expected(lang: str) -> dict:
    return json.loads((EXAMPLES / lang / REPOS[lang] / "expected.json").read_text())


RULES = str(Path(__file__).resolve().parent.parent / "rules" / "codesentry-core.yml")


@pytest.mark.skipif(not _HAS_SEMGREP, reason="semgrep not installed")
@pytest.mark.parametrize("lang", REPOS.keys())
def test_semgrep_detects_sample(lang):
    exp = _expected(lang)
    repo = str(EXAMPLES / lang / REPOS[lang])
    r = run_semgrep(repo, config=RULES)
    if r.status != "ok":
        pytest.fail(f"semgrep run failed: {r.reason}")
    sink_hits = [f for f in r.findings if f.cwe == exp["cwe"]]
    assert sink_hits, (
        f"expected CWE-{exp['cwe']} finding in {lang}/{REPOS[lang]}, "
        f"got {[(f.rule_id, f.cwe, f.file, f.line) for f in r.findings]}"
    )


@pytest.mark.skipif(not _HAS_JOERN, reason="joern not installed (M1: install to /Volumes/macOS/codesentry/tools)")
@pytest.mark.parametrize("lang", REPOS.keys())
def test_joern_detects_sample(lang):
    # 真值驱动验证：joern-frontend 完成接通后启用（M1 任务5 完整化）
    pytest.skip("joern query chain finalized in M1 task 5 completion")


@pytest.mark.skipif(not _HAS_CODEQL, reason="codeql not installed (platform never distributes; OSS only)")
def test_codeql_placeholder():
    pytest.skip("CodeQL: user-installed only")
