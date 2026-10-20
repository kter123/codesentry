import json

import httpx
import pytest

from codesentry.agents import llm as mod
from codesentry.agents.llm import LLMClient, LLMConfigError, LLMUnavailableError
from codesentry.control.profiles import LLMProfile


@pytest.fixture(autouse=True)
def _no_db_usage(monkeypatch):
    monkeypatch.setattr("codesentry.control.usage.record_usage", lambda **kw: True)


def _client(**kw):
    base = {
        "base_url": "https://example.test/v1",
        "api_key": "k",
        "fast_model": "f",
        "deep_model": "d",
        "temperature": 0.0,
        "retries": 2,
    }
    base.update(kw)
    return LLMClient(**base)


def test_legacy_signature_kept():
    c = _client()
    assert c.fast_model == "f" and c.deep_model == "d"
    assert c.protocol == "openai-compatible"


def test_prefix_strip():
    c = _client(deep_model="opencode-go/glm-5.3", model_prefix_policy="strip")
    seen = {}

    def fake(model, system, user):
        seen["model"] = model
        return "ok", "", 1, 1

    c._call_openai = fake  # type: ignore[method-assign]
    assert c.complete("s", "u") == "ok"
    assert seen["model"] == "glm-5.3"


def test_model_protocol_override():
    c = _client(model_protocols={"d": "anthropic-compatible"})
    called = {"anthropic": 0, "openai": 0}

    def fake_anthropic(model, system, user):
        called["anthropic"] += 1
        return "a", "", 1, 1

    def fake_openai(model, system, user):
        called["openai"] += 1
        return "o", "", 1, 1

    c._call_anthropic = fake_anthropic  # type: ignore[method-assign]
    c._call_openai = fake_openai  # type: ignore[method-assign]
    assert c.complete("s", "u") == "a"
    assert called == {"anthropic": 1, "openai": 0}


def test_anthropic_request_shape():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["headers"] = dict(req.headers)
        seen["body"] = json.loads(req.content)
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "thinking", "thinking": "why"},
                    {"type": "text", "text": "hello"},
                ],
                "usage": {"input_tokens": 3, "output_tokens": 2},
            },
        )

    c = _client(
        protocol="anthropic-compatible",
        extra_headers={"x-opencode-session": "s1"},
        transport=httpx.MockTransport(handler),
        deep_model="deepseek-v4-pro",
    )
    assert c.complete("sys", "user") == "hello"
    assert seen["url"].endswith("/messages")
    assert seen["headers"]["x-opencode-session"] == "s1"
    assert seen["body"]["model"] == "deepseek-v4-pro"
    assert seen["body"]["system"] == "sys"
    assert c.last_meta["reasoning"] == "why"
    assert c.last_meta["prompt_tokens"] == 3


def test_missing_session_is_config_error_no_retry():
    def handler(req):
        return httpx.Response(400, json={"error": {"type": "MissingSessionID", "message": "x"}})

    c = _client(protocol="anthropic-compatible", transport=httpx.MockTransport(handler), retries=3)
    with pytest.raises(LLMConfigError):
        c.complete("s", "u")


def test_429_retries_then_success(monkeypatch):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}],
                                         "usage": {"input_tokens": 1, "output_tokens": 1}})

    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    c = _client(protocol="anthropic-compatible", transport=httpx.MockTransport(handler), retries=2)
    assert c.complete("s", "u") == "ok"
    assert calls["n"] == 2


def test_fallback_client_used():
    primary = _client()
    fallback = _client()

    def boom(model, system, user):
        raise LLMUnavailableError("down")

    def ok(model, system, user):
        return "fallback", "", 1, 1

    primary._call_openai = boom  # type: ignore[method-assign]
    fallback._call_openai = ok  # type: ignore[method-assign]
    primary._fallback = fallback
    assert primary.complete("s", "u") == "fallback"


def test_probe_models():
    def handler(req):
        return httpx.Response(200, json={"data": [{"id": "glm-5.3"}, {"id": "kimi-k3"}]})

    c = _client(transport=httpx.MockTransport(handler))
    assert c.probe_models() == ["glm-5.3", "kimi-k3"]


def test_failed_call_is_recorded(monkeypatch):
    calls = []
    monkeypatch.setattr("codesentry.control.usage.record_usage", lambda **kw: calls.append(kw))

    def handler(req):
        return httpx.Response(401, json={"error": {"message": "unauthorized"}})

    c = _client(protocol="anthropic-compatible", transport=httpx.MockTransport(handler), retries=2)
    with pytest.raises(LLMConfigError):
        c.complete("s", "u")
    assert calls and calls[-1]["ok"] is False


def test_503_is_retried():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="service unavailable")
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}],
                                         "usage": {"input_tokens": 1, "output_tokens": 1}})

    c = _client(protocol="anthropic-compatible", transport=httpx.MockTransport(handler), retries=2)
    assert c.complete("s", "u") == "ok"
    assert calls["n"] == 2


def test_from_profile_builds_headers():
    p = LLMProfile(
        id=7, name="oc", protocol="openai-compatible", base_url="https://example.test/v1",
        fast_model="f", deep_model="d", extra_headers={"x-opencode-session": "${session_id}"},
        billing_mode="subscription",
    )
    c = LLMClient.from_profile(p, session_id="scan-1-triage-7")
    assert c.extra_headers["x-opencode-session"] == "scan-1-triage-7"
    assert c.profile_id == 7
    assert c.billing_mode == "subscription"
