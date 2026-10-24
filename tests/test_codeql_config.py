from types import SimpleNamespace

from codesentry.control import engine_config


def test_resolve_codeql_config_defaults(monkeypatch):
    monkeypatch.setattr(engine_config, "_setting", lambda key: "")
    monkeypatch.setattr(engine_config.shutil, "which", lambda name: "/opt/codeql/codeql")
    monkeypatch.setattr(engine_config, "_home_defaults", lambda: ("/nope/codeql", "/nope/packs"))
    monkeypatch.setattr(
        "codesentry.config.get_settings",
        lambda: SimpleNamespace(codeql_suite="", codeql_build_mode="none",
                                codeql_build_command="", codeql_timeout_s=1800,
                                codeql_db_cache=True, codeql_bin="codeql"),
    )
    cfg = engine_config.resolve_codeql_config("java")
    assert cfg.binary == "/opt/codeql/codeql"
    assert cfg.build_mode == "none"
    assert cfg.suite.startswith("codeql/java-queries:")


def test_resolve_codeql_config_explicit(monkeypatch):
    values = {
        "codeql_bin": "/custom/codeql",
        "codeql_search_path": "/packs",
        "codeql_suite": "codeql/java-queries:codeql-suites/java-security-extended.qls",
        "codeql_build_mode": "manual",
        "codeql_build_command": "mvn -q -DskipTests package",
        "codeql_timeout_s": "600",
    }
    monkeypatch.setattr(engine_config, "_setting", lambda key: values.get(key, ""))
    monkeypatch.setattr(
        "codesentry.config.get_settings",
        lambda: SimpleNamespace(codeql_suite="", codeql_build_mode="none",
                                codeql_build_command="", codeql_timeout_s=1800,
                                codeql_db_cache=True, codeql_bin="codeql"),
    )
    cfg = engine_config.resolve_codeql_config("java")
    assert cfg.binary == "/custom/codeql"
    assert cfg.search_path == "/packs"
    assert cfg.build_mode == "manual"
    assert cfg.timeout_s == 600
