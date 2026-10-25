import uuid

import pytest

from codesentry.agents import runtime
from codesentry.control.agent_config import get_agent_config
from codesentry.control.agent_presets import (
    bind_preset,
    create_preset,
    delete_preset,
    get_preset,
    update_preset,
)


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    monkeypatch.setenv("CODESENTRY_LLM_ENABLED", "false")
    monkeypatch.setattr("codesentry.agents.prompts.load_prompt",
                        lambda agent: ("BASE-PROMPT", None, True))
    monkeypatch.setattr("codesentry.control.skills.load_assigned_skills", lambda agent: [])


def test_preset_crud_version_and_bind(monkeypatch):
    name = f"preset-{uuid.uuid4().hex[:8]}"
    preset = create_preset(name, "triage", system_prompt="CUSTOM-RULES",
                           tools_allow=["graph_paths"], capabilities={"network": False})
    try:
        assert preset["version"] == 1
        updated = update_preset(preset["id"], {"system_prompt": "CUSTOM-RULES-V2"})
        assert updated and updated["version"] == 2
        assert get_preset(preset["id"])["system_prompt"] == "CUSTOM-RULES-V2"
        bound = bind_preset("triage", preset["id"])
        assert bound and bound["preset_id"] == preset["id"]
        rt = runtime.prepare_agent("triage", with_llm=False)
        assert "CUSTOM-RULES-V2" in rt.system_prompt
        assert "只输出 JSON" in rt.system_prompt
        assert "graph_paths" in rt.tools_allow
        assert rt.preset_id == preset["id"] and rt.preset_version == 2
        snap = rt.prompt_snapshot()["triage"]
        assert snap["preset_id"] == preset["id"] and snap["preset_version"] == 2
        bind_preset("triage", None)
        rt2 = runtime.prepare_agent("triage", with_llm=False)
        assert "CUSTOM-RULES-V2" not in rt2.system_prompt
        assert get_agent_config("triage")["preset_id"] is None
    finally:
        bind_preset("triage", None)
        delete_preset(preset["id"])


def test_preset_rejects_wrong_base_agent():
    with pytest.raises(ValueError):
        create_preset("bad", "not-an-agent", system_prompt="x")
    name = f"preset-{uuid.uuid4().hex[:8]}"
    preset = create_preset(name, "triage", system_prompt="x")
    try:
        with pytest.raises(ValueError):
            bind_preset("audit", preset["id"])
    finally:
        delete_preset(preset["id"])
