import json
import uuid

from codesentry.control import notifications, webhooks
from codesentry.db.pool import get_conn


def test_webhook_secret_encrypted_at_rest_and_hidden():
    name = f"hook-{uuid.uuid4().hex[:8]}"
    hook = webhooks.create_webhook(f"https://example.com/{name}", "topsecret",
                                   name=name, kind="generic")
    assert hook and hook["has_secret"] is True
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT secret FROM webhooks WHERE id=%s", (hook["id"],))
            stored = cur.fetchone()[0]
        assert stored.startswith("enc:")
        assert "topsecret" not in stored
        listed = webhooks.list_webhooks()
        row = next(h for h in listed if h["id"] == hook["id"])
        assert "secret" not in row and row["has_secret"] is True
    finally:
        webhooks.delete_webhook(hook["id"])


def test_notification_payloads():
    generic = {"id": 1, "kind": "generic", "url": "https://example.com/h",
               "secret": "s", "headers": {}}
    _url, body, headers = webhooks._payload_for(generic, "scan.completed",
                                                {"scan_id": 7})
    assert json.loads(body)["scan_id"] == 7
    assert headers["X-CodeSentry-Signature"].startswith("sha256=")

    feishu = {"id": 2, "kind": "feishu", "url": "https://example.com/f",
              "secret": "", "headers": {}}
    _url, body, _ = webhooks._payload_for(feishu, "scan.completed", {"scan_id": 7})
    assert json.loads(body)["msg_type"] == "text"

    ding = {"id": 3, "kind": "dingtalk", "url": "https://example.com/d?access_token=x",
            "secret": "s", "headers": {}}
    url, body, _ = webhooks._payload_for(ding, "scan.failed", {"error": "x"})
    assert "timestamp=" in url and "sign=" in url
    assert json.loads(body)["msgtype"] == "markdown"

    wecom = {"id": 4, "kind": "wecom", "url": "https://example.com/w",
             "secret": "", "headers": {}}
    _url, body, _ = webhooks._payload_for(wecom, "review.completed", {"kept": 2})
    assert json.loads(body)["markdown"]["content"]


def test_dispatch_updates_last_status(monkeypatch):
    name = f"disp-{uuid.uuid4().hex[:8]}"
    hook = webhooks.create_webhook(f"https://example.com/{name}", "",
                                   name=name, events=["scan.completed"])
    try:
        class R:
            status_code = 200

        monkeypatch.setattr(webhooks.httpx, "post", lambda *a, **k: R())
        out = webhooks.dispatch("scan.completed", {"scan_id": 1})
        assert any(item["ok"] for item in out if item["id"] == hook["id"])
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT last_status FROM webhooks WHERE id=%s", (hook["id"],))
            assert cur.fetchone()[0] == "ok"
    finally:
        webhooks.delete_webhook(hook["id"])


def test_email_uses_smtp(monkeypatch):
    sent = {}

    class SMTP:
        def __init__(self, host, port, timeout=10):
            sent["host"] = host
            sent["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, user, password):
            sent["login"] = (user, password)

        def send_message(self, msg):
            sent["subject"] = msg["Subject"]
            sent["to"] = msg["To"]

    monkeypatch.setattr(notifications.smtplib, "SMTP", SMTP)
    monkeypatch.setattr(notifications, "_setting", lambda key: {
        "smtp_host": "smtp.example.com", "smtp_port": "587", "smtp_user": "u",
        "smtp_password": "p", "smtp_from": "from@example.com",
        "smtp_to": "a@example.com", "smtp_tls": "true",
    }.get(key, ""))
    out = notifications.test_email()
    assert out["ok"] is True
    assert sent["host"] == "smtp.example.com"
    assert sent["to"] == "a@example.com"
    assert sent["subject"].startswith("CodeSentry")


def test_webhook_headers_are_redacted():
    name = f"hdr-{uuid.uuid4().hex[:8]}"
    hook = webhooks.create_webhook(f"https://example.com/{name}", "",
                                   name=name, headers={"Authorization": "Bearer x",
                                                       "to": "a@example.com"})
    try:
        row = next(h for h in webhooks.list_webhooks() if h["id"] == hook["id"])
        assert row["headers"]["Authorization"] == "***"
        assert row["headers"]["to"] == "a@example.com"
    finally:
        webhooks.delete_webhook(hook["id"])
