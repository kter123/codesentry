"""最小认证与 RBAC（M6.1 FR-27）：scrypt 密码、HS256 JWT、API Token、路径策略。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets as _secrets
import time
from datetime import UTC, datetime, timedelta

from codesentry.control.audit import audit_write
from codesentry.security.secrets import get_signing_key

ROLE_ORDER = {"viewer": 1, "analyst": 2, "admin": 3}
ROLES = set(ROLE_ORDER)
COOKIE_NAME = "cs_session"
JWT_TTL_SECONDS = 12 * 3600

PUBLIC_PATHS = {"/api/auth/login", "/api/auth/logout", "/api/health", "/openapi.json", "/docs", "/redoc"}
ADMIN_PREFIXES = (
    "/api/llm-profiles", "/api/agents", "/api/prompts", "/api/skills",
    "/api/rules", "/api/settings", "/api/users", "/api/api-tokens", "/api/usage",
    "/api/ops", "/api/webhooks", "/api/config",
)
ANALYST_PREFIXES = ("/api/scans", "/api/reviews")


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def hash_password(password: str) -> str:
    salt = _secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${_b64e(salt)}${_b64e(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(
            password.encode("utf-8"), salt=_b64d(salt_b64),
            n=int(n), r=int(r), p=int(p), dklen=len(_b64d(hash_b64)),
        )
        return hmac.compare_digest(dk, _b64d(hash_b64))
    except Exception:  # noqa: BLE001
        return False


def _user_public(row: tuple | dict) -> dict:
    if isinstance(row, dict):
        return {k: row[k] for k in ("id", "username", "display_name", "role", "enabled")}
    return {
        "id": int(row[0]), "username": row[1], "display_name": row[2] or "",
        "role": row[3], "enabled": bool(row[4]),
    }


def create_user(username: str, password: str, role: str = "viewer",
                display_name: str = "", actor: str = "system") -> dict | None:
    if not username or not password:
        raise ValueError("username/password 必填")
    if len(password) < 8:
        raise ValueError("密码至少 8 位")
    if role not in ROLES:
        raise ValueError(f"非法角色：{role}")
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, password_hash, display_name, role)"
                " VALUES (%s,%s,%s,%s) RETURNING id, username, display_name, role, enabled",
                (username, hash_password(password), display_name, role),
            )
            row = cur.fetchone()
            conn.commit()
        audit_write(actor, "create", "user", username, None,
                    {"username": username, "role": role})
        return _user_public(row)
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise ValueError("用户名已存在") from e
        return None


def get_user(username: str) -> dict | None:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, display_name, role, enabled, password_hash"
                " FROM users WHERE username=%s",
                (username,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {**_user_public(row[:5]), "password_hash": row[5]}
    except Exception:  # noqa: BLE001
        return None


def get_user_by_id(user_id: int) -> dict | None:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, display_name, role, enabled FROM users WHERE id=%s",
                (int(user_id),),
            )
            row = cur.fetchone()
        return _user_public(row) if row else None
    except Exception:  # noqa: BLE001
        return None


def list_users() -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, username, display_name, role, enabled FROM users ORDER BY id")
            return [_user_public(r) for r in cur.fetchall()]
    except Exception:  # noqa: BLE001
        return []


def update_user(user_id: int, patch: dict, actor: str = "system") -> dict | None:
    allowed = {"role", "enabled", "display_name"}
    payload = {k: patch[k] for k in allowed if k in patch}
    if "role" in payload and payload["role"] not in ROLES:
        raise ValueError("非法角色")
    if not payload:
        return get_user_by_id(user_id)
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        sets = ", ".join(f"{k}=%s" for k in payload)
        vals = list(payload.values()) + [int(user_id)]
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(f"UPDATE users SET {sets} WHERE id=%s", vals)
            conn.commit()
        after = get_user_by_id(user_id)
        audit_write(actor, "update", "user", str(user_id), None, after)
        return after
    except Exception:  # noqa: BLE001
        return None


def authenticate(username: str, password: str) -> dict | None:
    user = get_user(username)
    if not user or not user.get("enabled"):
        return None
    if not verify_password(password, user.get("password_hash", "")):
        return None
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE users SET last_login_at=now() WHERE id=%s", (user["id"],))
            conn.commit()
    except Exception:  # noqa: BLE001, S110
        pass
    return {k: v for k, v in user.items() if k != "password_hash"}


# ---- JWT ----
def issue_jwt(user: dict) -> str:
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "role": user.get("role", "viewer"),
        "iat": now,
        "exp": now + JWT_TTL_SECONDS,
    }
    h = _b64e(json.dumps(header, separators=(",", ":")).encode())
    p = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(get_signing_key(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{_b64e(sig)}"


def verify_jwt(token: str) -> dict | None:
    try:
        h, p, s = token.split(".")
        expected = hmac.new(get_signing_key(), f"{h}.{p}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64d(s)):
            return None
        payload = json.loads(_b64d(p))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:  # noqa: BLE001
        return None


# ---- API Token ----
def create_api_token(user_id: int | None, name: str, scopes: list[str] | None = None,
                     expires_days: int | None = None, actor: str = "system") -> dict | None:
    prefix = _secrets.token_hex(4)
    secret = _secrets.token_urlsafe(24)
    full = f"cs_{prefix}_{secret}"
    token_hash = hashlib.sha256(full.encode()).hexdigest()
    expires = datetime.now(UTC) + timedelta(days=expires_days) if expires_days else None
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO api_tokens (user_id, name, token_prefix, token_hash, scopes, expires_at)"
                " VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                (user_id, name, prefix, token_hash,
                 json.dumps(scopes or ["scan:read", "scan:write"]), expires),
            )
            tid = int(cur.fetchone()[0])
            conn.commit()
        audit_write(actor, "create", "api_token", str(tid), None, {"name": name, "prefix": prefix})
        return {"id": tid, "name": name, "token": full, "prefix": prefix,
                "scopes": scopes or ["scan:read", "scan:write"],
                "expires_at": str(expires) if expires else None}
    except Exception:  # noqa: BLE001
        return None


def list_api_tokens() -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, name, token_prefix, scopes, expires_at, last_used_at, created_at"
                " FROM api_tokens ORDER BY id"
            )
            rows = cur.fetchall()
        return [
            {"id": r[0], "user_id": r[1], "name": r[2], "prefix": r[3], "scopes": r[4],
             "expires_at": str(r[5]) if r[5] else None,
             "last_used_at": str(r[6]) if r[6] else None, "created_at": str(r[7])}
            for r in rows
        ]
    except Exception:  # noqa: BLE001
        return []


def revoke_api_token(token_id: int, actor: str = "system") -> bool:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM api_tokens WHERE id=%s", (int(token_id),))
            conn.commit()
        audit_write(actor, "revoke", "api_token", str(token_id), None, None)
        return True
    except Exception:  # noqa: BLE001
        return False


def verify_api_token(token: str) -> dict | None:
    if not token.startswith("cs_"):
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT t.id, t.user_id, t.name, t.scopes, t.expires_at, u.enabled"
                " FROM api_tokens t LEFT JOIN users u ON u.id=t.user_id"
                " WHERE t.token_hash=%s",
                (token_hash,),
            )
            row = cur.fetchone()
            if not row:
                return None
            if row[1] is not None and row[5] is False:
                return None
            if row[4] is not None and row[4] < datetime.now(UTC):
                return None
            cur.execute("UPDATE api_tokens SET last_used_at=now() WHERE id=%s", (row[0],))
            conn.commit()
        return {
            "id": row[0], "user_id": row[1], "username": f"token:{row[2]}",
            "role": "ci", "scopes": row[3] or [], "name": row[2],
        }
    except Exception:  # noqa: BLE001
        return None


def bootstrap_admin() -> dict | None:
    """认证开启且无用户时，用 CODESENTRY_ADMIN_PASSWORD 引导管理员。"""
    if list_users():
        return None
    password = os.environ.get("CODESENTRY_ADMIN_PASSWORD", "")
    if not password:
        return None
    username = os.environ.get("CODESENTRY_ADMIN_USER", "admin")
    try:
        return create_user(username, password, role="admin", display_name="Administrator",
                           actor="bootstrap")
    except ValueError:
        return None


# ---- 路径策略 ----
def required_role(method: str, path: str) -> str:
    if path.startswith(("/api/users", "/api/api-tokens")):
        return "admin"
    if path.startswith("/api/audit"):
        return "analyst" if method in ("GET", "HEAD", "OPTIONS") else "admin"
    if path.startswith("/api/usage") and method in ("GET", "HEAD", "OPTIONS"):
        return "viewer"
    if method in ("GET", "HEAD", "OPTIONS"):
        return "analyst" if path.startswith(ADMIN_PREFIXES) else "viewer"
    if path.startswith(ADMIN_PREFIXES):
        return "admin"
    if path.startswith(ANALYST_PREFIXES):
        return "analyst"
    return "viewer"


def role_ok(user: dict, needed: str, method: str, path: str) -> bool:
    role = user.get("role", "viewer")
    if role == "ci":
        scopes = set(user.get("scopes") or [])
        readable = path.startswith(("/api/scans", "/api/reports", "/api/findings"))
        if method in ("GET", "HEAD", "OPTIONS"):
            return readable and bool({"scan:read", "report:read"} & scopes)
        if method == "POST" and path.rstrip("/") == "/api/scans":
            return "scan:write" in scopes
        return False
    return ROLE_ORDER.get(role, 0) >= ROLE_ORDER.get(needed, 99)


def resolve_identity(authorization: str | None, cookie: str | None) -> dict | None:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token.startswith("cs_"):
            return verify_api_token(token)
    if cookie:
        payload = verify_jwt(cookie)
        if payload:
            user = get_user_by_id(int(payload["sub"]))
            if user and user.get("enabled"):
                return user
    return None
