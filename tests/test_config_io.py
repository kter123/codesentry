import uuid

from codesentry.control import config_io
from codesentry.control.agent_config import get_agent_config
from codesentry.db.pool import get_conn


def test_export_redacts_secrets():
    key = f"test_{uuid.uuid4().hex[:6]}_api_key"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO app_settings (key, value) VALUES (%s,%s)"
            " ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
            (key, "super-secret"),
        )
        cur.execute(
            "INSERT INTO app_settings (key, value) VALUES ('codeql_build_command','mvn -Dtoken=x')"
            " ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value"
        )
        conn.commit()
    try:
        doc = config_io.export_config()
        assert doc["schema_version"] == 1
        assert key not in doc["settings"]
        assert "codeql_build_command" not in doc["settings"]
        for hook in doc["webhooks"]:
            assert "secret" not in hook
    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM app_settings WHERE key=%s", (key,))
            conn.commit()


def test_import_merge_prompt_and_agent():
    agent = "report"
    previous = get_agent_config(agent)
    version = 900000 + uuid.uuid4().int % 1000
    doc = {
        "schema_version": 1,
        "prompts": [{"agent": agent, "version": version, "body": "IMPORTED-PROMPT",
                     "active": False}],
        "agents": [{"name": agent, "timeout_s": 123, "tools_allow": ["read_source"]}],
        "settings": {"codeql_build_command": "should-not-import"},
    }
    try:
        out = config_io.import_config(doc, "merge")
        assert out["counts"]["prompts"] == 1
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT body FROM prompt_versions WHERE agent=%s AND version=%s",
                        (agent, version))
            assert cur.fetchone()[0] == "IMPORTED-PROMPT"
            cur.execute("SELECT value FROM app_settings WHERE key='codeql_build_command'")
            row = cur.fetchone()
            assert not row or row[0] != "should-not-import"
        cfg = get_agent_config(agent)
        assert cfg["timeout_s"] == 123
        assert cfg["tools_allow"] == ["read_source"]
    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM prompt_versions WHERE agent=%s AND version=%s",
                        (agent, version))
            conn.commit()
        from codesentry.control.agent_config import update_agent_config

        update_agent_config(agent, {
            "timeout_s": previous["timeout_s"],
            "tools_allow": previous["tools_allow"],
        })


def test_import_rejects_bad_schema():
    try:
        config_io.import_config({"schema_version": 999})
        raise AssertionError("should reject")
    except ValueError:
        pass
