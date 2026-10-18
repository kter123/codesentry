import json

from typer.testing import CliRunner

import codesentry.cli as cli_mod
import codesentry.scan_orchestrator as so
from codesentry.models import EngineResult, Finding

runner = CliRunner()


def _mock_one_finding(monkeypatch):
    def fake_run_engines(specs, **kw):
        return [
            EngineResult(engine="semgrep", status="ok",
                         findings=[Finding(rule_id="t/1", cwe=79, severity="low",
                                           confidence=0.5, file="x.py", line=1,
                                           message="m", engine="semgrep")])
        ]

    monkeypatch.setattr(so, "run_engines_parallel", fake_run_engines)


def test_scan_writes_reports(tmp_path, monkeypatch):
    _mock_one_finding(monkeypatch)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "x.py").write_text("x = 1\n")
    out = tmp_path / "out"
    r = runner.invoke(cli_mod.app, ["scan", str(repo), "--out", str(out)])
    assert r.exit_code == 0, r.output
    files = {p.name for p in out.iterdir()}
    assert "report.sarif" in files and "report.md" in files
    sarif = json.loads((out / "report.sarif").read_text())
    assert sarif["version"] == "2.1.0"
    md = (out / "report.md").read_text()
    assert "t/1" in md


def test_scan_closed_source_metadata(tmp_path, monkeypatch):
    _mock_one_finding(monkeypatch)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "x.py").write_text("x = 1\n")
    out = tmp_path / "out"
    r = runner.invoke(cli_mod.app, ["scan", str(repo), "--out", str(out)])  # 无 --oss → 闭源
    assert r.exit_code == 0, r.output
    md = (out / "report.md").read_text()
    assert "闭源" in md


def test_scan_oss_all_engines_dead_aborts(tmp_path, monkeypatch):
    # 三引擎全失败 → 中止该扫描并落因（§10）
    def all_dead(specs, **kw):
        return [
            EngineResult(engine="codeql", status="unavailable", reason="gate"),
            EngineResult(engine="joern", status="unavailable", reason="not found"),
            EngineResult(engine="semgrep", status="crashed", reason="exit 1"),
        ]

    monkeypatch.setattr(so, "run_engines_parallel", all_dead)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "x.py").write_text("x = 1\n")
    r = runner.invoke(cli_mod.app, ["scan", str(repo), "--out", str(tmp_path / "o2")])
    assert r.exit_code != 0
    assert "semgrep" in (r.output + str(r.exception)).lower() or "失败" in r.output
