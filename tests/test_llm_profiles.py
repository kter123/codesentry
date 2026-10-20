import uuid

import pytest

from codesentry.control import profiles
from codesentry.db.pool import get_conn


def _name() -> str:
    return f"unit-{uuid.uuid4().hex[:8]}"


def _cleanup(ids: list[int], agents: list[str]) -> None:
    with get_conn() as c, c.cursor() as cur:
        for a in agents:
            cur.execute("UPDATE agent_configs SET llm_profile_id=NULL WHERE name=%s", (a,))
        for pid in ids:
            cur.execute("DELETE FROM llm_profiles WHERE id=%s", (pid,))
        c.commit()


def _ensure_agent(name: str) -> None:
    with get_conn() as c, c.cursor() as cur:
        cur.execute("INSERT INTO agent_configs (name) VALUES (%s) ON CONFLICT DO NOTHING", (name,))
        c.commit()


def test_create_encrypts_and_masks():
    name = _name()
    p = profiles.create_profile(
        {"name": name, "base_url": "https://example.com/v1", "fast_model": "f",
         "deep_model": "d", "api_key": "sk-super-secret-123"}
    )
    assert p and p.id
    try:
        with get_conn() as c, c.cursor() as cur:
            cur.execute("SELECT api_key_cipher FROM llm_profiles WHERE id=%s", (p.id,))
            cipher = cur.fetchone()[0]
        assert cipher and "sk-super-secret" not in cipher
        pub = profiles.to_public(profiles.get_profile(p.id))
        assert pub["api_key"].endswith("…")
        assert "sk-super-secret" not in str(pub)
    finally:
        _cleanup([p.id], [])


def test_update_empty_key_keeps_cipher():
    name = _name()
    p = profiles.create_profile(
        {"name": name, "base_url": "https://example.com/v1", "fast_model": "f",
         "deep_model": "d", "api_key": "sk-keep-me-123456"}
    )
    assert p and p.id
    try:
        before = profiles.get_profile(p.id).api_key_cipher
        profiles.update_profile(p.id, {"api_key": "", "temperature": 0.2})
        after = profiles.get_profile(p.id)
        assert after.api_key_cipher == before
        assert after.temperature == 0.2
    finally:
        _cleanup([p.id], [])


def test_default_is_unique():
    prev = profiles.get_default()
    ids = []
    try:
        a = profiles.create_profile({"name": _name(), "base_url": "https://a/v1", "fast_model": "f",
                                     "deep_model": "d", "is_default": True})
        b = profiles.create_profile({"name": _name(), "base_url": "https://b/v1", "fast_model": "f",
                                     "deep_model": "d", "is_default": True})
        ids = [a.id, b.id]
        defaults = [p for p in profiles.list_profiles() if p.is_default]
        assert len(defaults) == 1
        assert defaults[0].id == b.id
    finally:
        _cleanup(ids, [])
        if prev is not None:
            profiles.set_default(prev.id, actor="test")


def test_bind_resolve_and_delete_bound():
    name = _name()
    p = profiles.create_profile({"name": name, "base_url": "https://example.com/v1",
                                 "fast_model": "f", "deep_model": "d"})
    assert p and p.id
    try:
        _ensure_agent("triage")
        with get_conn() as c, c.cursor() as cur:
            cur.execute("UPDATE agent_configs SET llm_profile_id=%s WHERE name='triage'", (p.id,))
            c.commit()
        got, source = profiles.resolve_profile("triage")
        assert got and got.id == p.id and source == "agent"
        assert profiles.delete_profile(p.id) == "bound"
        assert "triage" in profiles.bound_agents(p.id)
    finally:
        _cleanup([p.id], ["triage"])


def test_fallback_when_bound_disabled():
    p1 = profiles.create_profile({"name": _name(), "base_url": "https://a/v1",
                                  "fast_model": "f", "deep_model": "d"})
    p2 = profiles.create_profile({"name": _name(), "base_url": "https://b/v1",
                                  "fast_model": "f", "deep_model": "d"})
    try:
        profiles.update_profile(p1.id, {"fallback_profile_id": p2.id})
        _ensure_agent("triage")
        with get_conn() as c, c.cursor() as cur:
            cur.execute("UPDATE agent_configs SET llm_profile_id=%s WHERE name='triage'", (p1.id,))
            c.commit()
        profiles.update_profile(p1.id, {"enabled": False})
        got, source = profiles.resolve_profile("triage")
        assert got and got.id == p2.id and source == "fallback"
    finally:
        _cleanup([p1.id, p2.id], ["triage"])


def test_opencode_go_preset_shape():
    preset = profiles.PRESETS["opencode-go"]
    assert preset["base_url"] == "https://opencode.ai/zen/go/v1"
    assert preset["extra_headers"]["x-opencode-session"] == "${session_id}"
    assert preset["billing_mode"] == "subscription"
    assert preset["quota_windows"]


def test_extra_headers_reject_secret_keys():
    with pytest.raises(ValueError, match="extra_headers"):
        profiles.create_profile({
            "name": _name(), "base_url": "https://example.test/v1",
            "fast_model": "f", "deep_model": "d",
            "extra_headers": {"Authorization": "Bearer x"},
        })
