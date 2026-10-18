from codesentry.models import EngineResult, Finding
from codesentry.scan_orchestrator import run_engines_parallel, select_engines


def test_parallel_two_engines():
    def fake_a(**kw):
        return EngineResult(engine="joern", status="ok",
                            findings=[Finding(rule_id="j1", cwe=79, severity="medium",
                                              confidence=0.7, file="a", line=1,
                                              message="m", engine="joern")])

    def fake_b(**kw):
        return EngineResult(engine="semgrep", status="ok", findings=[])

    results = run_engines_parallel(specs=[fake_a, fake_b])
    assert [r.engine for r in results] == ["joern", "semgrep"]


def test_one_crash_does_not_block_other():
    def fake_a(**kw):
        raise RuntimeError("boom")

    def fake_b(**kw):
        return EngineResult(engine="semgrep", status="ok", findings=[])

    results = run_engines_parallel(specs=[fake_a, fake_b])
    assert len(results) == 2
    statuses = {r.engine: r.status for r in results}
    assert statuses.get("semgrep") == "ok"
    assert any(s in ("crashed", "timeout") for s in statuses.values())


def test_engine_selection_by_license():
    oss, prop = select_engines(OSS=True), select_engines(OSS=False)
    assert "codeql" in oss and "codeql" not in prop
    assert "semgrep" in oss and "semgrep" in prop


def test_engine_selection_lang_php_no_codeql():
    oss = select_engines(OSS=True, lang="php")
    assert "codeql" not in oss  # §4.2 PHP 无 CodeQL
    prop = select_engines(OSS=False, lang="php")
    assert "codeql" not in prop
