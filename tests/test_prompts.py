from codesentry.agents.prompts import SEED_PROMPTS, load_prompt


def test_seed_all_agents():
    assert set(SEED_PROMPTS) == {"recon", "scan", "audit", "retrieval", "triage", "deploy", "poc_gen", "report"}


def test_load_prompt_fallback_no_db(monkeypatch):
    monkeypatch.setenv("CODESENTRY_DATABASE_URL", "postgresql://codesentry:bad-pass@127.0.0.1:5499/missing")
    text, version, fallback = load_prompt("triage")
    assert fallback is True
    assert "TriageAgent" in text
    assert version is None
