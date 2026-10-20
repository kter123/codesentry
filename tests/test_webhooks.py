import hashlib
import hmac
import json

from codesentry.control import webhooks
from codesentry.db.pool import get_conn


def _cleanup(url: str) -> None:
    with get_conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM webhooks WHERE url=%s", (url,))
        c.commit()


def test_webhook_crud_and_signature(monkeypatch):
    url = "https://example.test/hook"
    _cleanup(url)
    try:
        hook = webhooks.create_webhook(url, "s3cret", ["scan.completed"], actor="test")
        assert hook and hook["id"]
        seen = {}

        class R:
            status_code = 200

        def fake_post(u, content=None, headers=None, timeout=None):
            seen.update({"url": u, "content": content, "headers": headers})
            return R()

        monkeypatch.setattr("codesentry.control.webhooks.httpx.post", fake_post)
        res = webhooks.dispatch("scan.completed", {"scan_id": 7, "ok": True})
        assert any(r.get("ok") for r in res)
        body = json.dumps({"scan_id": 7, "ok": True}, ensure_ascii=False, sort_keys=True).encode()
        expected = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        assert seen["headers"]["X-CodeSentry-Signature"] == expected
        assert seen["headers"]["X-CodeSentry-Event"] == "scan.completed"
    finally:
        _cleanup(url)


def test_webhook_rejects_bad_url():
    try:
        webhooks.create_webhook("ftp://x", actor="test")
        raise AssertionError("should reject")
    except ValueError:
        pass
