from types import SimpleNamespace

import pytest

from codesentry.agents import runtime
from codesentry.agents.skills import Skill
from codesentry.db.pool import get_conn


def _skill():
    s = Skill(name="taint", description="d", body="BODY", body_tokens_est=1)
    s.version = 2
    s.body_sha256 = "a" * 64
    return s


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setenv("CODESENTRY_LLM_ENABLED", "true")
    monkeypatch.setattr("codesentry.agents.prompts.load_prompt", lambda agent: ("SYS", 3, False))
    monkeypatch.setattr("codesentry.control.skills.load_assigned_skills", lambda agent: [_skill()])
    monkeypatch.setattr(
        "codesentry.control.agent_config.get_agent_config",
        lambda agent: {"enabled": True, "model_role": "deep", "llm_profile_id": 9},
    )
    monkeypatch.setattr(
        "codesentry.control.agent_config.effective_capabilities",
        lambda agent: {"engines": [], "network": False, "shell": False, "poc_exec": False},
    )
    fake = SimpleNamespace(profile_id=9, deep_model="d", fast_model="f",
                           protocol="openai-compatible", billing_mode="subscription")
    monkeypatch.setattr(
        "codesentry.agents.llm.LLMClient.for_agent",
        classmethod(lambda cls, *a, **k: fake),
    )
    return fake


def test_prepare_agent_merges_prompt_and_skills(patched):
    rt = runtime.prepare_agent("triage", scan_id=1)
    assert rt.enabled is True
    assert "SYS" in rt.system()
    assert "BODY" in rt.system()
    assert rt.prompt_version == 3
    assert rt.profile_id == 9
    assert rt.state_updates()["prompt_versions"] == {"triage": {"version": 3}}
    assert rt.state_updates()["skills_snapshot"]["triage"][0]["name"] == "taint"
    assert rt.llm_snapshot()["triage"]["profile_id"] == 9


def test_disabled_has_no_llm(patched, monkeypatch):
    monkeypatch.setattr(
        "codesentry.control.agent_config.get_agent_config",
        lambda agent: {"enabled": False, "model_role": "deep", "llm_profile_id": None},
    )
    rt = runtime.prepare_agent("triage")
    assert rt.enabled is False and rt.llm is None


def test_llm_failure_degrades(patched, monkeypatch):
    def boom(cls, *a, **k):
        raise RuntimeError("no db")

    monkeypatch.setattr("codesentry.agents.llm.LLMClient.for_agent", classmethod(boom))
    rt = runtime.prepare_agent("triage")
    assert rt.llm is None
    assert any("LLM 不可用" in w for w in rt.warnings)


def test_prompt_fallback_warns(patched, monkeypatch):
    monkeypatch.setattr("codesentry.agents.prompts.load_prompt", lambda agent: ("SEED", None, True))
    rt = runtime.prepare_agent("triage")
    assert rt.prompt_fallback is True
    assert any("回退" in w for w in rt.warnings)
    assert rt.prompt_snapshot() == {}


def test_snapshot_pins_prompt_version():
    from codesentry.control import prompts

    agent = "triage"
    prev = prompts.get_versions(agent)
    prev_active = next((v["version"] for v in prev if v["active"]), None)
    v1 = None
    try:
        v1 = prompts.create_version(agent, "SNAP-PROMPT")
        prompts.create_version(agent, "LIVE-PROMPT")
        snapshot = {"prompt_versions": {agent: {"version": v1}},
                    "skills_snapshot": {}, "llm_snapshot": {}}
        rt = runtime.prepare_agent(agent, with_llm=False, snapshot=snapshot)
        assert "SNAP-PROMPT" in rt.system_prompt
        assert "LIVE-PROMPT" not in rt.system_prompt
        assert rt.prompt_version == v1
    finally:
        if v1 is not None:
            with get_conn() as c, c.cursor() as cur:
                cur.execute("DELETE FROM prompt_versions WHERE agent=%s AND version>=%s", (agent, v1))
                c.commit()
            if prev_active is not None:
                prompts.activate(agent, prev_active)
