"""六语言×引擎覆盖矩阵逐组合验证（agent.md §4.2）。

运行时探测 binary（不用 import-time 常量，避免 monkeypatch/PATH 变化带来缓存）。
joern 真跑（joern-parse + 查询脚本已实测）；codeql 用户自装探测。
"""

import json
import shutil
from pathlib import Path

import pytest

from codesentry.engines.joern import run_joern
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
RULES = str(Path(__file__).resolve().parent.parent / "rules" / "codesentry-core.yml")


def _has(binary: str) -> bool:
    return shutil.which(binary) is not None


def _expected(lang: str) -> dict:
    return json.loads((EXAMPLES / lang / REPOS[lang] / "expected.json").read_text())


@pytest.mark.skipif(not _has("semgrep"), reason="semgrep not installed")
@pytest.mark.parametrize("lang", REPOS.keys())
def test_semgrep_detects_sample(lang):
    exp = _expected(lang)
    repo = str(EXAMPLES / lang / REPOS[lang])
    r = run_semgrep(repo, config=RULES)
    if r.status != "ok":
        pytest.fail(f"semgrep run failed: {r.reason}")
    hit = [f for f in r.findings if f.cwe == exp["cwe"]]
    assert hit, (
        f"expected CWE-{exp['cwe']} in {lang}/{REPOS[lang]}, "
        f"got {[(f.rule_id, f.cwe, f.file, f.line) for f in r.findings]}"
    )


@pytest.mark.skipif(not _has("joern"), reason="joern not installed")
@pytest.mark.parametrize("lang", REPOS.keys())
def test_joern_detects_sample(lang):
    exp = _expected(lang)
    repo = str(EXAMPLES / lang / REPOS[lang])
    r = run_joern(repo=repo, lang=lang, out_dir="/tmp/joern-matrix")
    if r.status != "ok":
        if lang == "php":
            # §4.2：php2cpg 实验性——实测崩溃，显式降级（扫描元数据标注；不影响本验证集断言）
            pytest.xfail("php2cpg experimental frontend crashes (agent.md §4.2 known; degrade to semgrep)")
        pytest.fail(f"joern run failed: {r.reason}")
    hit = [f for f in r.findings if f.cwe == exp["cwe"]]
    assert hit, (
        f"expected CWE-{exp['cwe']} via joern in {lang}/{REPOS[lang]}, "
        f"got {[(f.rule_id, f.cwe, f.line) for f in r.findings]}"
    )
