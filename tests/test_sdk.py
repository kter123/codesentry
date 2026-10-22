import httpx

from codesentry.sdk import CodeSentryClient


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
