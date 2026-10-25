import httpx

from codesentry.sdk import CodeSentryClient


def test_sdk_paths_and_config():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.path, str(req.url.query)))
        if req.url.path.endswith("/paths"):
            return httpx.Response(200, json={"paths": [{"id": 1}]})
        if req.url.path.endswith("/paths/1"):
            return httpx.Response(200, json={"id": 1, "nodes_detail": []})
        if req.url.path.endswith("/coverage"):
            return httpx.Response(200, json={"total": 3})
        if req.url.path.endswith("/codeql/status"):
            return httpx.Response(200, json={"found": True})
        if req.url.path.endswith("/codeql/test"):
            return httpx.Response(200, json={"ok": True})
        if req.url.path.endswith("/config/export"):
            return httpx.Response(200, json={"schema_version": 1})
        if req.url.path.endswith("/config/import"):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    c = CodeSentryClient(base_url="http://test", transport=httpx.MockTransport(handler))
    try:
        assert c.list_paths(7, status="pending", limit=5)["paths"][0]["id"] == 1
        assert c.get_path(7, 1)["id"] == 1
        assert c.coverage(7)["total"] == 3
        assert c.codeql_status()["found"] is True
        assert c.engine_test()["ok"] is True
        assert c.export_config()["schema_version"] == 1
        assert c.import_config({"schema_version": 1})["ok"] is True
    finally:
        c.close()
    assert any("status=pending" in q and "limit=5" in q for _m, _p, q in calls)


def test_sdk_usage(monkeypatch):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rows": []})

    c = CodeSentryClient(base_url="http://test", transport=httpx.MockTransport(handler))
    try:
        assert c.usage("agent") == {"rows": []}
    finally:
        c.close()


def test_sdk_health_and_scan(monkeypatch):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["headers"] = dict(req.headers)
        if req.url.path == "/api/health":
            return httpx.Response(200, json={"db": {"ok": True}})
        if req.url.path == "/api/scans":
            return httpx.Response(200, json={"scan_id": 7})
        return httpx.Response(404)

    c = CodeSentryClient(base_url="http://test", token="cs_x", transport=httpx.MockTransport(handler))
    try:
        assert c.health()["db"]["ok"] is True
        assert c.create_scan(diff_text="x")["scan_id"] == 7
        assert seen["headers"]["authorization"] == "Bearer cs_x"
        assert "diff_text=x" in seen["url"]
    finally:
        c.close()
