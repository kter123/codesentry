import json

from typer.testing import CliRunner

import codesentry.cli as cli_mod
import codesentry.orchestrator.runner as runner_mod
from codesentry.models import Finding

runner = CliRunner()


def _mock_one_finding(monkeypatch):
    def fake_run_scan_graph(repo, OSS, out_dir):
        # 最小编排回放：直接产出报告（模拟成功 scan）
        from pathlib import Path

        from codesentry.reportex.markdown import render_markdown
        from codesentry.reportex.sarif import write_sarif

        f = Finding(rule_id="t/1", cwe=79, severity="low", confidence=0.5,
                    file="x.py", line=1, message="m", engine="semgrep")
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        write_sarif([f], str(Path(out_dir) / "report.sarif"))
        (Path(out_dir) / "report.md").write_text(
            render_markdown([f], profile_languages=["python"],
                            license_declaration={"OSS": OSS, "declared_at": "t"}),
            encoding="utf-8",
        )
        return 0

    monkeypatch.setattr(runner_mod, "run_scan_graph", fake_run_scan_graph)


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
    r = runner.invoke(cli_mod.app, ["scan", str(repo), "--out", str(tmp_path / "o1")])  # 无 --oss → 闭源
    assert r.exit_code == 0, r.output
    md = (tmp_path / "o1" / "report.md").read_text()
    assert "闭源" in md


def test_scan_runner_failure_exits_nonzero(tmp_path, monkeypatch):
    def fail(repo, OSS, out_dir):
        raise RuntimeError("simulated-scan-dead")

    monkeypatch.setattr(runner_mod, "run_scan_graph", fail)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "x.py").write_text("x = 1\n")
    r = runner.invoke(cli_mod.app, ["scan", str(repo), "--out", str(tmp_path / "o2")])
    assert r.exit_code != 0
