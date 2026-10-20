from codesentry.control import bootstrap


def test_bootstrap_idempotent():
    assert bootstrap.ensure_control_schema(force=True) is True
    assert bootstrap.ensure_control_schema() is True
    assert bootstrap.ensure_control_schema(force=True) is True


def test_bootstrap_no_db(monkeypatch):
    bootstrap.reset_cache()
    monkeypatch.setenv("CODESENTRY_DATABASE_URL", "postgresql://x:y@127.0.0.1:1/none")
    assert bootstrap.ensure_control_schema(force=True) is False
