
from codesentry.control.engine_config import CodeQLConfig
from codesentry.engines import codeql


def test_run_codeql_command_construction(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "A.java").write_text("class A { void f() {} }", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    cfg = CodeQLConfig(
        binary="/bin/echo", search_path="/packs",
        suite="codeql/java-queries:codeql-suites/java-security-extended.qls",
        build_mode="none", build_command="", timeout_s=30, cache=False,
    )
    monkeypatch.setattr("codesentry.control.engine_config.resolve_codeql_config",
                        lambda lang: cfg)
    cmds: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        cmds.append(list(cmd))
        return type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(codeql.subprocess, "run", fake_run)
    monkeypatch.setattr(codeql, "_parse_sarif", lambda path: [])
    result = codeql.run_codeql(str(repo), "java", True, str(out))
    assert result.status == "ok"
    create = cmds[0]
    assert "--build-mode=none" in create
    assert "--search-path" in create and "/packs" in create
    assert "--overwrite" in create
    analyze = cmds[1]
    assert analyze[-1].endswith("java-security-extended.qls")


def test_run_codeql_unavailable_without_binary(monkeypatch, tmp_path):
    cfg = CodeQLConfig(binary="", search_path="", suite="s", build_mode="none",
                       build_command="", timeout_s=30, cache=True)
    monkeypatch.setattr("codesentry.control.engine_config.resolve_codeql_config",
                        lambda lang: cfg)
    monkeypatch.setattr(codeql.shutil, "which", lambda name: None)
    result = codeql.run_codeql(str(tmp_path), "java", True, str(tmp_path))
    assert result.status == "unavailable"
