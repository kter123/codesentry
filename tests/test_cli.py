import pytest
from typer.testing import CliRunner

import codesentry.cli as cli_mod

runner = CliRunner()

ALL_COMMANDS = ["init-db", "scan", "diff", "report", "kb", "engines", "agents", "skills"]
PLACEHOLDER_COMMANDS = ["scan", "diff", "report", "kb", "agents", "skills"]


@pytest.mark.parametrize("cmd", ALL_COMMANDS)
def test_subcommand_registered(cmd):
    result = runner.invoke(cli_mod.app, [cmd, "--help"])
    assert result.exit_code == 0, f"命令 {cmd} 未注册"


@pytest.mark.parametrize("cmd", PLACEHOLDER_COMMANDS)
def test_placeholder_exits_1_with_hint(cmd):
    result = runner.invoke(cli_mod.app, [cmd])
    assert result.exit_code == 1, f"{cmd} 未实现却 exit {result.exit_code}"
    assert "未实现" in result.output
    assert "agent.md" in result.output


def test_engines_check_reports_probe(monkeypatch):
    monkeypatch.setattr("codesentry.cli_commands.shutil.which", lambda name: f"/fake/path/{name}")
    result = runner.invoke(cli_mod.app, ["engines"])
    assert result.exit_code == 0
    for name in ("codeql", "joern", "semgrep", "java"):
        assert name in result.output


def test_engines_check_missing_exits_1(monkeypatch):
    monkeypatch.setattr("codesentry.cli_commands.shutil.which", lambda name: None)
    result = runner.invoke(cli_mod.app, ["engines"])
    assert result.exit_code == 1
