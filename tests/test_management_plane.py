import pytest

from codesentry.agents.prompts import (
    INVARIANT_MARKER,
    compose_prompt,
    render_prompt,
)
from codesentry.control import llm_pool


def test_prompt_render_strict_and_invariants():
    assert render_prompt("agent={{agent}}", {"agent": "triage"}) == "agent=triage"
    with pytest.raises(KeyError):
        render_prompt("{{missing_var}}", {})
    text = compose_prompt("triage", "你是 Triage。", {"agent": "triage"})
    assert INVARIANT_MARKER in text
    assert "不可信数据" in text
    assert "verdict" in text


def test_llm_pool_chain_order(monkeypatch):
    class P:
        def __init__(self, pid, priority=0, exclude=False, default=False, enabled=True):
            self.id, self.priority, self.pool_exclude = pid, priority, exclude
            self.is_default, self.enabled, self.name = default, enabled, f"p{pid}"

    profiles = [P(1, priority=5), P(2, priority=10), P(3, exclude=True), P(4, default=True)]
    monkeypatch.setattr("codesentry.control.profiles.list_profiles", lambda: profiles)
    monkeypatch.setattr("codesentry.control.profiles.get_profile",
                        lambda pid: next((p for p in profiles if p.id == int(pid)), None))
    chain = llm_pool.chain_profiles(2)
    assert [p.id for p in chain] == [2, 1, 4]


def test_circuit_breaker_open_and_reset(monkeypatch):
    monkeypatch.setattr(llm_pool, "_persist", lambda pid, state: None)
    llm_pool._STATE.pop(999999, None)
    assert llm_pool.is_open(999999) is False
    tripped = llm_pool.record_failure(999999, "HTTP 401 unauthorized", hard=True)
    assert tripped is True
    assert llm_pool.is_open(999999) is True
    llm_pool.reset(999999)
    assert llm_pool.is_open(999999) is False
    assert llm_pool._STATE[999999]["fails"] == 0
