from codesentry.engines.codeql import run_codeql
from codesentry.engines.joern import run_joern


def test_codeql_missing_bin_degrades(monkeypatch, tmp_path):
    monkeypatch.setenv("CODESENTRY_CODEQL_BIN", "codesentry-nonexistent-_xyz")
    r = run_codeql(repo=str(tmp_path), lang="python", OSS=True, out_dir=str(tmp_path))
    assert r.status == "unavailable"
    assert "not found" in (r.reason or "").lower()


def test_joern_missing_bin_degrades(monkeypatch, tmp_path):
    monkeypatch.setenv("CODESENTRY_JOERN_BIN", "codesentry-nonexistent-_xyz")
    r = run_joern(repo=str(tmp_path), lang="python", out_dir=str(tmp_path))
    assert r.status == "unavailable"
