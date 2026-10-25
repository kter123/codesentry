from fastapi.testclient import TestClient

from codesentry.web.server import app

client = TestClient(app)


def test_compare_dry_run_does_not_call_llm(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("LLM should not be called")

    monkeypatch.setattr("codesentry.agents.llm.LLMClient.for_agent", classmethod(boom))
    res = client.post("/api/agents/triage/compare", json={"state": {"finding": {}}})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["used_llm"] is False
    assert body["a"]["token_est"] > 0 and body["b"]["token_est"] > 0
    assert "system" not in body["a"]


def test_compare_invalid_version_400():
    res = client.post("/api/agents/triage/compare", json={"prompt_a": 999999})
    assert res.status_code == 400
