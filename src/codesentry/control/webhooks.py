"""Webhook / 通知渠道（M6.6 + 2026-10-25 P1）：HMAC、飞书/钉钉/企微、加密 secret。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

import httpx

KINDS = ("generic", "feishu", "dingtalk", "wecom", "email")


def _encrypt(secret: str) -> str:
    if not secret:
        return ""
    if secret.startswith("enc:"):
        return secret
    from codesentry.security.secrets import encrypt_secret

    return "enc:" + encrypt_secret(secret)


def _decrypt(secret: str) -> str:
    if not secret:
        return ""
    if not secret.startswith("enc:"):
        return secret  # 兼容旧明文
    try:
        from codesentry.security.secrets import decrypt_secret

        return decrypt_secret(secret[4:])
    except Exception:  # noqa: BLE001 - 密钥轮换后无法签名，按无 secret 处理
        return ""


def _hooks_with_secret() -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, kind, url, secret, events, headers, enabled"
                " FROM webhooks ORDER BY id"
            )
            rows = cur.fetchall()
        return [
            {"id": r[0], "name": r[1] or "", "kind": r[2] or "generic", "url": r[3],
             "secret": _decrypt(r[4] or ""), "events": r[5] or ["*"],
             "headers": r[6] or {}, "enabled": bool(r[7])}
            for r in rows
        ]
    except Exception:  # noqa: BLE001
        return []


def _public_headers(headers: dict | None) -> dict:
    out: dict[str, str] = {}
    for key, value in (headers or {}).items():
        low = str(key).lower()
        if any(part in low for part in ("authorization", "token", "secret", "api-key",
                                        "apikey", "password")):
            out[str(key)] = "***"
        else:
            out[str(key)] = str(value)
    return out


def list_webhooks() -> list[dict]:
    return [
        {**{k: v for k, v in h.items() if k not in ("secret", "headers")},
         "headers": _public_headers(h.get("headers")),
         "has_secret": bool(h.get("secret"))}
        for h in _hooks_with_secret()
    ]


def create_webhook(url: str, secret: str = "", events: list[str] | None = None,
                   actor: str = "api", *, name: str = "", kind: str = "generic",
                   headers: dict[str, str] | None = None) -> dict | None:
    kind = str(kind or "generic").lower()
    if kind not in KINDS:
        raise ValueError(f"未知通知渠道：{kind}")
    if kind == "email":
        url = url or "smtp"
    if not url.startswith(("http://", "https://")) and kind != "email":
        raise ValueError("url 必须是 http(s)")
    try:
        from codesentry.control.audit import audit_write
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO webhooks (name, kind, url, secret, events, headers)"
                " VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                (name, kind, url, _encrypt(secret), json.dumps(events or ["*"]),
                 json.dumps(headers or {})),
            )
            wid = int(cur.fetchone()[0])
            conn.commit()
        audit_write(actor, "create", "webhook", str(wid), None,
                    {"name": name, "kind": kind, "url": url, "events": events})
        return {"id": wid, "name": name, "kind": kind, "url": url,
                "events": events or ["*"], "has_secret": bool(secret)}
    except Exception as e:
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


def _text(event: str, payload: dict[str, Any]) -> str:
    bits = [f"[CodeSentry] {event}"]
    for key in ("scan_id", "repo", "status", "kept", "target_url", "error"):
        if payload.get(key) not in (None, ""):
            bits.append(f"{key}: {payload[key]}")
    if len(bits) == 1:
        bits.append(json.dumps(payload, ensure_ascii=False)[:800])
    return "\n".join(bits)


def _feishu_body(text: str, secret: str) -> dict[str, Any]:
    body: dict[str, Any] = {"msg_type": "text", "content": {"text": text}}
    if secret:
        ts = str(int(time.time()))
        raw = f"{ts}\n{secret}".encode()
        sign_value = base64.b64encode(
            hmac.new(raw, digestmod=hashlib.sha256).digest()
        ).decode()
        body.update({"timestamp": ts, "sign": sign_value})
    return body


def _dingtalk_url(url: str, secret: str) -> str:
    if not secret:
        return url
    ts = str(int(time.time() * 1000))
    raw = f"{ts}\n{secret}".encode()
    sig = base64.b64encode(
        hmac.new(secret.encode(), raw, hashlib.sha256).digest()
    ).decode()
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}timestamp={ts}&sign={sig}"


def _dingtalk_body(text: str) -> dict[str, Any]:
    return {"msgtype": "markdown", "markdown": {"title": "CodeSentry", "text": text}}


def _wecom_body(text: str) -> dict[str, Any]:
    return {"msgtype": "markdown", "markdown": {"content": text}}


def _payload_for(hook: dict, event: str, payload: dict) -> tuple[str, bytes, dict[str, str]]:
    kind = str(hook.get("kind") or "generic")
    text = _text(event, payload)
    secret = str(hook.get("secret") or "")
    headers = {"Content-Type": "application/json",
               **{str(k): str(v) for k, v in (hook.get("headers") or {}).items()}}
    url = str(hook["url"])
    if kind == "feishu":
        body = json.dumps(_feishu_body(text, secret), ensure_ascii=False).encode()
    elif kind == "dingtalk":
        body = json.dumps(_dingtalk_body(text), ensure_ascii=False).encode()
        url = _dingtalk_url(url, secret)
    elif kind == "wecom":
        body = json.dumps(_wecom_body(text), ensure_ascii=False).encode()
    else:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        sig = sign(secret, body)
        if sig:
            headers["X-CodeSentry-Signature"] = sig
    headers["X-CodeSentry-Event"] = event
    return url, body, headers


def _record(hook_id: int, ok: bool, detail: str) -> None:
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE webhooks SET last_status=%s, last_error=%s, last_sent_at=now()"
                " WHERE id=%s",
                ("ok" if ok else "failed", "" if ok else detail[:300], int(hook_id)),
            )
            conn.commit()
    except Exception:  # noqa: BLE001, S110
        pass


def _send(hook: dict, event: str, payload: dict, retries: int) -> dict:
    url, body, headers = _payload_for(hook, event, payload)
    last_err = ""
    for attempt in range(max(1, retries + 1)):
        try:
            r = httpx.post(url, content=body, headers=headers, timeout=10)
            if 200 <= r.status_code < 300:
                _record(int(hook["id"]), True, "")
                return {"id": hook["id"], "kind": hook.get("kind"), "ok": True,
                        "status": r.status_code}
            last_err = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last_err = str(e)[:160]
        if attempt < retries:
            time.sleep(1.0 * (attempt + 1))
    _record(int(hook["id"]), False, last_err)
    return {"id": hook["id"], "kind": hook.get("kind"), "ok": False, "error": last_err}


def _matches(hook: dict, event: str) -> bool:
    events = hook.get("events") or ["*"]
    return "*" in events or event in events


def dispatch(event: str, payload: dict, retries: int = 2) -> list[dict]:
    """向匹配事件的 webhook 投递；email 渠道由 notifications 模块处理。"""
    out: list[dict] = []
    for hook in _hooks_with_secret():
        if not hook["enabled"] or not _matches(hook, event):
            continue
        if hook.get("kind") == "email":
            continue
        out.append(_send(hook, event, payload, retries))
    return out


def test_webhook(webhook_id: int) -> dict:
    hook = next((h for h in _hooks_with_secret() if int(h["id"]) == int(webhook_id)), None)
    if hook is None:
        raise ValueError("webhook not found")
    if hook.get("kind") == "email":
        from codesentry.control.notifications import send_email

        return send_email("CodeSentry 测试通知", "这是一条 CodeSentry 测试通知。", hook)
    return _send(hook, "test", {"message": "CodeSentry test notification"}, retries=0)
