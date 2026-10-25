"""受限远程 PoC 目标（P2）：登记/过期/只读探测；不执行 finding payload。"""

from __future__ import annotations

import ipaddress
import socket
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx


def _bad_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any((ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_reserved,
                ip.is_unspecified, ip.is_multicast))


def _setting(key: str) -> str:
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT value FROM app_settings WHERE key=%s", (key,))
            row = cur.fetchone()
        if row is not None:
            return str(row[0])
    except Exception:  # noqa: BLE001, S110
        pass
    from codesentry.config import get_settings

    return str(getattr(get_settings(), key, "") or "")


def _allow_private() -> bool:
    return _setting("poc_remote_allow_private").lower() in ("1", "true", "yes", "on")


def _enabled() -> bool:
    return _setting("poc_remote_enabled").lower() in ("1", "true", "yes", "on")


def validate_target_url(url: str, allowed_hosts: list[str] | None = None) -> str:
    if not _enabled():
        raise ValueError("远程 PoC target 未启用（POC_REMOTE_ENABLED=false）")
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("target 必须是 https")
    host = parsed.hostname.lower()
    if allowed_hosts and not any(
        host == h.lower() or host.endswith("." + h.lower().lstrip("."))
        for h in allowed_hosts
    ):
        raise ValueError("target host 不在 allowed_hosts")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(i[4][0])
                         for i in socket.getaddrinfo(host, None)]
        except OSError as e:
            raise ValueError("target host 解析失败") from e
    if not _allow_private() and any(_bad_ip(ip) for ip in addresses):
        raise ValueError("target 解析到私网/回环地址")
    return url.rstrip("/")


def list_targets() -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, base_url, allowed_hosts, expires_at, enabled, created_at"
                " FROM poc_targets ORDER BY id"
            )
            rows = cur.fetchall()
        return [{"id": r[0], "name": r[1], "base_url": r[2], "allowed_hosts": r[3],
                 "expires_at": str(r[4]) if r[4] else None, "enabled": bool(r[5]),
                 "created_at": str(r[6])} for r in rows]
    except Exception:  # noqa: BLE001
        return []


def create_target(name: str, base_url: str, allowed_hosts: list[str],
                  expires_at: datetime | None = None, enabled: bool = True) -> dict:
    if not str(name).strip():
        raise ValueError("名称必填")
    base_url = validate_target_url(base_url, allowed_hosts)
    from codesentry.control.audit import audit_write
    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.db.pool import get_conn

    ensure_control_schema()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO poc_targets (name, base_url, allowed_hosts, expires_at, enabled)"
            " VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (name.strip(), base_url, ",".join(allowed_hosts), expires_at, bool(enabled)),
        )
        tid = int(cur.fetchone()[0])
        conn.commit()
    audit_write("api", "create", "poc_target", str(tid), None,
                {"name": name, "base_url": base_url})
    return next(t for t in list_targets() if int(t["id"]) == tid)


def delete_target(target_id: int) -> bool:
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM poc_targets WHERE id=%s", (int(target_id),))
        ok = cur.rowcount > 0
        conn.commit()
    return ok


def authorized_target(target_id: int) -> dict | None:
    row = next((t for t in list_targets() if int(t["id"]) == int(target_id)), None)
    if not row or not row["enabled"]:
        return None
    if row.get("expires_at"):
        try:
            expires = datetime.fromisoformat(str(row["expires_at"]))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            if expires < datetime.now(UTC):
                return None
        except ValueError:
            return None
    return row


def probe_target(target_id: int) -> dict:
    row = authorized_target(target_id)
    if not row:
        raise ValueError("target 不存在/未启用/已过期")
    # 只读探测：不执行 finding payload，不跟随重定向
    url = str(row["base_url"]).rstrip("/") + "/"
    try:
        r = httpx.get(url, timeout=5.0, follow_redirects=False)
        return {"ok": True, "target_id": target_id, "url": url,
                "status_code": r.status_code, "content_type": r.headers.get("content-type", "")}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "target_id": target_id, "url": url,
                "error": str(e)[:200]}
