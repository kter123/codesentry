from codesentry.agents import scan as scan_mod
from codesentry.agents.state import new_state


def test_scan_respects_engine_allowlist(monkeypatch):
    monkeypatch.setattr(scan_mod, "select_engines", lambda OSS, lang: ["semgrep", "joern"])
    seen = []

    def fake_parallel(specs):
        seen.extend(s.__name__ for s in specs)
        return []

    monkeypatch.setattr(scan_mod, "run_engines_parallel", fake_parallel)
    monkeypatch.setattr(
        "codesentry.control.agent_config.effective_capabilities",
        lambda name: {"engines": ["semgrep"]},
    )
    s = new_state("/tmp/repo", OSS=False)
    s["profile"] = {"languages": ["python"]}
    u = scan_mod.run_scan_agent(s)
    assert seen == ["run_semgrep"]
    assert u["engine_findings"] == []
