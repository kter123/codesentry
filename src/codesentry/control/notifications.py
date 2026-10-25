"""统一通知分发：webhook 渠道 + SMTP 邮件（P1）。"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

SMTP_KEYS = (
    "smtp_host", "smtp_port", "smtp_user", "smtp_password",
    "smtp_from", "smtp_to", "smtp_tls",
)


def _setting(key: str) -> str:
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT value FROM app_settings WHERE key=%s", (key,))
            row = cur.fetchone()
        if row is not None:
            value = str(row[0])
            if key == "smtp_password" and value:
                from codesentry.security.secrets import SecretError, decrypt_secret

                try:
                    return decrypt_secret(value)
                except SecretError:
                    return ""
            return value
    except Exception:  # noqa: BLE001, S110
        pass
    import os

    return os.environ.get(f"CODESENTRY_{key.upper()}", "")


def smtp_config() -> dict[str, Any]:
    port_raw = _setting("smtp_port") or "587"
    try:
        port = int(port_raw)
    except ValueError:
        port = 587
    return {
        "host": _setting("smtp_host"),
        "port": port,
        "user": _setting("smtp_user"),
        "password": _setting("smtp_password"),
        "from": _setting("smtp_from"),
        "to": _setting("smtp_to"),
        "tls": (_setting("smtp_tls") or "true").lower() not in ("0", "false", "no", "off"),
    }


def _recipients(hook: dict | None = None) -> list[str]:
    raw = ""
    if hook:
        raw = str((hook.get("headers") or {}).get("to") or "")
    raw = raw or str(smtp_config().get("to") or "")
    return [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]


def send_email(subject: str, body: str, hook: dict | None = None) -> dict:
    cfg = smtp_config()
    recipients = _recipients(hook)
    if not cfg["host"] or not recipients:
        return {"ok": False, "kind": "email",
                "error": "SMTP 未配置或收件人为空"}
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["from"] or cfg["user"] or "codesentry@localhost"
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)
    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=10) as smtp:
            if cfg["tls"]:
                smtp.starttls()
            if cfg["user"]:
                smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
        return {"ok": True, "kind": "email", "to": recipients}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "kind": "email", "error": str(e)[:200]}


def dispatch_all(event: str, payload: dict, retries: int = 2) -> list[dict]:
    from codesentry.control.webhooks import (
        _hooks_with_secret,
        _matches,
        _text,
        dispatch,
    )

    out = dispatch(event, payload, retries)
    for hook in _hooks_with_secret():
        if not hook.get("enabled") or hook.get("kind") != "email":
            continue
        if not _matches(hook, event):
            continue
        out.append(send_email(f"CodeSentry {event}", _text(event, payload), hook))
    return out


def test_email() -> dict:
    return send_email("CodeSentry 测试邮件", "这是一条 CodeSentry SMTP 测试通知。")
