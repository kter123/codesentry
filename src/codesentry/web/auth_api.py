"""M6.1 认证 API 与中间件（可开关，默认关闭以兼容本地模式）。"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from codesentry.control import auth
from codesentry.web.server import app

_FAILS: dict[str, list[float]] = defaultdict(list)
_FAILS_LOCK = Lock()
_MAX_FAILS = 5
_FAIL_WINDOW_S = 300


def _throttled(key: str) -> bool:
    now = time.time()
    with _FAILS_LOCK:
        recent = [t for t in _FAILS.get(key, []) if now - t < _FAIL_WINDOW_S]
        _FAILS[key] = recent
        return len(recent) >= _MAX_FAILS


def _record_fail(key: str) -> None:
    now = time.time()
    with _FAILS_LOCK:
        _FAILS[key].append(now)
        if len(_FAILS) > 1000:
            for k in list(_FAILS):
                _FAILS[k] = [t for t in _FAILS[k] if now - t < _FAIL_WINDOW_S]
                if not _FAILS[k]:
                    _FAILS.pop(k, None)


def _clear_fail(key: str) -> None:
    with _FAILS_LOCK:
        _FAILS.pop(key, None)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    from codesentry.config import get_settings

    if not get_settings().auth_enabled or request.method == "OPTIONS":
        from codesentry.control.audit import set_actor

        set_actor("local")
        return await call_next(request)
    path = request.url.path
    if path in auth.PUBLIC_PATHS or path.startswith(("/docs", "/openapi")):
        return await call_next(request)
    if not path.startswith("/api"):
        return await call_next(request)
    user = auth.resolve_identity(
        request.headers.get("authorization"), request.cookies.get(auth.COOKIE_NAME)
    )
    if not user:
        return JSONResponse({"detail": "未认证"}, status_code=401)
    needed = auth.required_role(request.method, path)
    if not auth.role_ok(user, needed, request.method, path):
        return JSONResponse({"detail": "权限不足"}, status_code=403)
    request.state.user = user
    from codesentry.control.audit import set_actor

    set_actor(str(user.get("username") or ""))
    return await call_next(request)


@app.on_event("startup")
async def _bootstrap_auth() -> None:
    from codesentry.config import get_settings

    if get_settings().auth_enabled:
        auth.bootstrap_admin()


@app.post("/api/auth/login")
async def login(request: Request, response: Response) -> dict:
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        data = await request.json()
    else:
        data = dict(await request.form())
    username = str(data.get("username") or "")
    password = str(data.get("password") or "")
    client = request.client.host if request.client else "unknown"
    key = f"{client}:{username}"
    if _throttled(key):
        raise HTTPException(429, "登录尝试次数过多，请稍后再试")
    user = auth.authenticate(username, password)
    if user is None:
        _record_fail(key)
        raise HTTPException(401, "用户名或密码错误")
    _clear_fail(key)
    token = auth.issue_jwt(user)
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        key=auth.COOKIE_NAME, value=token, httponly=True, samesite="lax",
        secure=secure, max_age=auth.JWT_TTL_SECONDS,
    )
    return {"ok": True, "user": user}


@app.post("/api/auth/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


@app.get("/api/auth/me")
async def me(request: Request) -> dict:
    from codesentry.config import get_settings

    if not get_settings().auth_enabled:
        return {"username": "local", "role": "admin", "auth_enabled": False}
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "未认证")
    return {"user": user, "auth_enabled": True}


class UserPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    username: str
    password: str
    role: str = "viewer"
    display_name: str = ""


class UserPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str | None = None
    enabled: bool | None = None
    display_name: str | None = None


@app.get("/api/users")
async def list_users() -> dict:
    return {"users": auth.list_users()}


@app.post("/api/users")
async def create_user(payload: UserPayload) -> dict:
    try:
        user = auth.create_user(
            payload.username, payload.password, role=payload.role,
            display_name=payload.display_name, actor="api",
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if user is None:
        raise HTTPException(503, "用户创建失败（DB 不可用？）")
    return {"user": user}


@app.put("/api/users/{user_id}")
async def update_user(user_id: int, payload: UserPatch) -> dict:
    try:
        user = auth.update_user(user_id, payload.model_dump(exclude_unset=True), actor="api")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if user is None:
        if auth.get_user_by_id(user_id) is None:
            raise HTTPException(404)
        raise HTTPException(503, "用户写入失败（DB 不可用？）")
    return {"user": user}


class TokenPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    user_id: int | None = None
    scopes: list[str] | None = None
    expires_days: int | None = None


@app.get("/api/api-tokens")
async def list_tokens() -> dict:
    return {"tokens": auth.list_api_tokens()}


@app.post("/api/api-tokens")
async def create_token(payload: TokenPayload) -> dict:
    token = auth.create_api_token(
        payload.user_id, payload.name, payload.scopes, payload.expires_days, actor="api"
    )
    if token is None:
        raise HTTPException(503, "Token 创建失败（DB 不可用？）")
    return {"token": token}


@app.post("/api/api-tokens/{token_id}/revoke")
async def revoke_token(token_id: int) -> dict:
    if not auth.revoke_api_token(token_id, actor="api"):
        raise HTTPException(404)
    return {"ok": True}
