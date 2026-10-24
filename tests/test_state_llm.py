import os

import pytest

from codesentry.agents.llm import LLMClient, LLMError
from codesentry.agents.state import AGENT_NAMES, new_state


def _clean(monkeypatch):
    for k in list(os.environ):
        if k.startswith("CODESENTRY_"):
            monkeypatch.delenv(k)


def test_new_state_defaults():
    s = new_state("/repo", OSS=False)
    assert s["repo_path"] == "/repo"
    assert s["license_declaration"]["OSS"] is False
    assert s["budget"]["phase"] == "ok"
    assert s["phase"] == "recon"
    assert s["replan_count"] == 0


def test_state_fields_complete():
    s = new_state("/r", OSS=True)
    for field in ("evidence", "poc_results", "prompt_versions", "skills_snapshot", "messages", "engine_findings", "triaged_findings"):
        assert field in s
    assert set(AGENT_NAMES) == {"recon", "scan", "audit", "triage", "deploy", "poc_gen", "report"}


def test_llm_requires_config(monkeypatch):
    _clean(monkeypatch)
    # settings 可能从 .env 读到配置——显式封空环境变量保证「未配置」前提
    monkeypatch.setenv("CODESENTRY_MODEL_BASE_URL", "")
    monkeypatch.setenv("CODESENTRY_FAST_MODEL", "")
    monkeypatch.setenv("CODESENTRY_DEEP_MODEL", "")
    with pytest.raises(LLMError, match="LLM"):
        LLMClient.from_config()


def test_llm_env_override(monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("CODESENTRY_MODEL_BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("CODESENTRY_FAST_MODEL", "f")
    monkeypatch.setenv("CODESENTRY_DEEP_MODEL", "d")
    c = LLMClient.from_config()
    assert c.fast_model == "f" and c.deep_model == "d"


def test_llm_retry_three_then_raise(monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("CODESENTRY_MODEL_BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("CODESENTRY_FAST_MODEL", "f")
    monkeypatch.setenv("CODESENTRY_DEEP_MODEL", "d")
    c = LLMClient.from_config()
    # 快退避：直接把 delays 打短
    import codesentry.agents.llm as llm_mod

    real_sleep = llm_mod.time.sleep
    llm_mod.time.sleep = lambda s: None  # type: ignore[assignment]
    try:
        with pytest.raises(LLMError, match="重试"):
            c.complete("sys", "user")
    finally:
        llm_mod.time.sleep = real_sleep
