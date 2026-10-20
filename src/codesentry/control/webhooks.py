"""Webhook 通知（M6.6）：HMAC-SHA256 签名、事件过滤、重试。"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx


def _hooks_with_secret() -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, url, secret, events, enabled FROM webhooks ORDER BY id")
            rows = cur.fetchall()
        return [{"id": r[0], "url": r[1], "secret": r[2], "events": r[3],
                 "enabled": bool(r[4])} for r in rows]
    except Exception:  # noqa: BLE001
        return []


def list_webhooks() -> list[dict]:
    return [{k: v for k, v in h.items() if k != "secret"} for h in _hooks_with_secret()]


def create_webhook(url: str, secret: str = "", events: list[str] | None = None,
                   actor: str = "api") -> dict | None:
    if not url.startswith(("http://", "https://")):
        raise ValueError("url 必须是 http(s)")
    try:
        from codesentry.control.audit import audit_write
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO webhooks (url, secret, events) VALUES (%s,%s,%s) RETURNING id",
                (url, secret, json.dumps(events or ["*"])),
            )
            wid = int(cur.fetchone()[0])
            conn.commit()
        audit_write(actor, "create", "webhook", str(wid), None, {"url": url, "events": events})
        return {"id": wid, "url": url, "events": events or ["*"]}
    except Exception as e:  # noqa: BLE001
        if isinstance(e, ValueError):
            raise
        return None


def delete_webhook(webhook_id: int, actor: str = "api") -> bool:
    try:
        from codesentry.control.audit import audit_write
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM webhooks WHERE id=%s", (int(webhook_id),))
            conn.commit()
        audit_write(actor, "delete", "webhook", str(webhook_id), None, None)
        return True
    except Exception:  # noqa: BLE001
        return False


def sign(secret: str, body: bytes) -> str:
    if not secret:
        return ""
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def dispatch(event: str, payload: dict, retries: int = 2) -> list[dict]:
    """向匹配事件的 webhook 投递；返回每个目标的投递结果。"""
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    out: list[dict] = []
    for hook in _hooks_with_secret():
        if not hook["enabled"]:
            continue
        events = hook.get("events") or ["*"]
        if "*" not in events and event not in events:
            continue
        headers = {"Content-Type": "application/json", "X-CodeSentry-Event": event}
        sig = sign(str(hook.get("secret") or ""), body)
        if sig:
            headers["X-CodeSentry-Signature"] = sig
        last_err = ""
        for attempt in range(max(1, retries + 1)):
            try:
                r = httpx.post(str(hook["url"]), content=body, headers=headers, timeout=10)
                if 200 <= r.status_code < 300:
                    out.append({"id": hook["id"], "ok": True, "status": r.status_code})
                    break
                last_err = f"HTTP {r.status_code}"
            except Exception as e:  # noqa: BLE001
                last_err = str(e)[:160]
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
        else:
            out.append({"id": hook["id"], "ok": False, "error": last_err})
    return out
