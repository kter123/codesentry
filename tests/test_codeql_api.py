from fastapi.testclient import TestClient

from codesentry.db.pool import get_conn
from codesentry.web.server import app

client = TestClient(app)


def test_codeql_settings_roundtrip():
    values = {
        "codeql_bin": "/tmp/codeql",
        "codeql_search_path": "/tmp/packs",
        "codeql_suite": "codeql/java-queries:codeql-suites/java-security-extended.qls",
        "codeql_build_mode": "none",
        "codeql_build_command": "",
        "codeql_timeout_s": "600",
        "codeql_db_cache": "true",
    }
    try:
        r = client.put("/api/settings/codeql", json={"values": values})
        assert r.status_code == 200, r.text
        got = client.get("/api/settings/codeql").json()
        assert got["codeql_bin"] == "/tmp/codeql"
        assert got["codeql_build_mode"] == "none"
    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM app_settings WHERE key LIKE 'codeql_%'")
            conn.commit()


def test_codeql_status_and_test_endpoints(monkeypatch):
    fake = {"found": True, "binary": "/opt/codeql", "version": "2.27.2",
            "search_path": "/packs", "suite": "s", "build_mode": "none",
            "languages": ["java"], "packs": ["codeql"], "error": ""}
    monkeypatch.setattr("codesentry.control.engine_config.codeql_status",
                        lambda lang="java": fake)
    status = client.get("/api/engines/codeql/status").json()
    assert status["found"] is True and status["version"] == "2.27.2"
    test = client.post("/api/engines/codeql/test").json()
    assert test["ok"] is True
    health = client.get("/api/health").json()
    assert health["engine_details"]["codeql"]["found"] is True
