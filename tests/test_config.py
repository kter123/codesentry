import os

from codesentry.config import Settings


def _fresh(monkeypatch):
    for k in list(os.environ):
        if k.startswith("CODESENTRY_"):
            monkeypatch.delenv(k)
    return Settings(_env_file=None)


def test_budget_defaults(monkeypatch):
    s = _fresh(monkeypatch)
    assert s.max_tokens == 500_000
    assert s.max_tool_calls == 500
    assert s.max_cost_usd == 10.0
    assert s.max_findings == 200


def test_switch_defaults(monkeypatch):
    s = _fresh(monkeypatch)
    assert s.human_review is False
    assert s.temperature == 0.0
    assert s.poc_run == "off"
    assert s.web_bind == "0.0.0.0"
    assert s.work_dir == ".codesentry"
    assert s.allow_oss_codeql is False


def test_env_override(monkeypatch):
    monkeypatch.setenv("CODESENTRY_MAX_TOKENS", "1000")
    s = Settings(_env_file=None)
    assert s.max_tokens == 1000


def test_engines_bin_paths(monkeypatch):
    s = _fresh(monkeypatch)
    assert s.codeql_bin == "codeql"
    assert s.joern_bin == "joern"
    assert s.semgrep_bin == "semgrep"
