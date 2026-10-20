"""LLM Profile 服务（M6.1 FR-20）：CRUD、默认/fallback、绑定解析、探测。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from codesentry.control.audit import audit_write
from codesentry.security.secrets import encrypt_secret, mask_cipher

_ALLOWED_PROTOCOLS = {"openai-compatible", "anthropic-compatible"}
_FIELDS = (
    "name", "provider", "protocol", "model_prefix_policy", "base_url", "fast_model",
    "deep_model", "temperature", "max_tokens", "timeout_s", "max_concurrency",
    "input_price_per_1k", "output_price_per_1k", "capabilities", "extra_headers",
    "model_catalog", "model_protocols", "quota_windows", "billing_mode",
    "fallback_profile_id", "enabled", "is_default",
)
_JSON_FIELDS = {"capabilities", "extra_headers", "model_catalog", "model_protocols", "quota_windows"}

_COLUMNS = (
    "id, name, provider, protocol, model_prefix_policy, base_url, api_key_cipher,"
    " fast_model, deep_model, temperature, max_tokens, timeout_s, max_concurrency,"
    " input_price_per_1k, output_price_per_1k, capabilities, extra_headers, model_catalog,"
    " model_protocols, quota_windows, billing_mode, fallback_profile_id, enabled,"
    " is_default, created_at, updated_at"
)

PRESETS: dict[str, dict[str, Any]] = {
    "openai": {
        "provider": "openai-compatible",
        "protocol": "openai-compatible",
        "base_url": "https://api.openai.com/v1",
        "billing_mode": "metered",
    },
    "anthropic": {
        "provider": "anthropic-compatible",
        "protocol": "anthropic-compatible",
        "base_url": "https://api.anthropic.com/v1",
        "billing_mode": "metered",
    },
    "ollama": {
        "provider": "ollama",
        "protocol": "openai-compatible",
        "base_url": "http://127.0.0.1:11434/v1",
        "billing_mode": "local",
    },
    "azure": {
        "provider": "azure",
        "protocol": "openai-compatible",
        "base_url": "",
        "billing_mode": "metered",
    },
    "opencode-go": {
        "provider": "opencode-go",
        "protocol": "openai-compatible",
        "base_url": "https://opencode.ai/zen/go/v1",
        "model_prefix_policy": "strip",
        "extra_headers": {"x-opencode-session": "${session_id}"},
        "billing_mode": "subscription",
        "quota_windows": [
            {"window": "5h", "usd": 12},
            {"window": "week", "usd": 30},
            {"window": "month", "usd": 60},
        ],
    },
}


@dataclass
class LLMProfile:
    id: int | None = None
    name: str = ""
    provider: str = "openai-compatible"
    protocol: str = "openai-compatible"
    model_prefix_policy: str = "strip"
    base_url: str = ""
    api_key_cipher: str = ""
    fast_model: str = ""
    deep_model: str = ""
    temperature: float = 0.0
    max_tokens: int = 0
    timeout_s: int = 60
    max_concurrency: int = 4
    input_price_per_1k: float = 0.0
    output_price_per_1k: float = 0.0
    capabilities: dict = field(default_factory=dict)
    extra_headers: dict = field(default_factory=dict)
    model_catalog: list = field(default_factory=list)
    model_protocols: dict = field(default_factory=dict)
    quota_windows: list = field(default_factory=list)
    billing_mode: str = "metered"
    fallback_profile_id: int | None = None
    enabled: bool = True
    is_default: bool = False
    created_at: str | None = None
    updated_at: str | None = None


def _row_to_profile(row: tuple) -> LLMProfile:
    keys = (
        "id", "name", "provider", "protocol", "model_prefix_policy", "base_url",
        "api_key_cipher", "fast_model", "deep_model", "temperature", "max_tokens",
        "timeout_s", "max_concurrency", "input_price_per_1k", "output_price_per_1k",
        "capabilities", "extra_headers", "model_catalog", "model_protocols",
        "quota_windows", "billing_mode", "fallback_profile_id", "enabled", "is_default",
        "created_at", "updated_at",
    )
    d = dict(zip(keys, row))
    for k in ("created_at", "updated_at"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    return LLMProfile(**d)


def to_public(p: LLMProfile) -> dict:
    """对外表示：只返回密钥掩码，绝不返回密文。"""
    return {
        "id": p.id,
        "name": p.name,
        "provider": p.provider,
        "protocol": p.protocol,
        "model_prefix_policy": p.model_prefix_policy,
        "base_url": p.base_url,
        "api_key": mask_cipher(p.api_key_cipher),
        "fast_model": p.fast_model,
        "deep_model": p.deep_model,
        "temperature": p.temperature,
        "max_tokens": p.max_tokens,
        "timeout_s": p.timeout_s,
        "max_concurrency": p.max_concurrency,
        "input_price_per_1k": p.input_price_per_1k,
        "output_price_per_1k": p.output_price_per_1k,
        "capabilities": p.capabilities or {},
        "extra_headers": p.extra_headers or {},
        "model_catalog": p.model_catalog or [],
        "model_protocols": p.model_protocols or {},
        "quota_windows": p.quota_windows or [],
        "billing_mode": p.billing_mode,
        "fallback_profile_id": p.fallback_profile_id,
        "enabled": p.enabled,
        "is_default": p.is_default,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


def _validate(data: dict) -> str | None:
    base = str(data.get("base_url") or "")
    if base and not base.startswith(("http://", "https://")):
        return "base_url 必须是 http(s) URL"
    protocol = str(data.get("protocol") or "openai-compatible")
    if protocol not in _ALLOWED_PROTOCOLS:
        return f"不支持的 protocol: {protocol}"
    headers = data.get("extra_headers") or {}
    if isinstance(headers, dict):
        for key in headers:
            low = str(key).lower()
            if any(s in low for s in ("authorization", "api-key", "apikey", "cookie", "secret")):
                return "extra_headers 不允许包含密钥类请求头（请使用 api_key 字段）"
    return None


def _jsonify(key: str, value: Any) -> Any:
    return json.dumps(value, ensure_ascii=False) if key in _JSON_FIELDS else value


def list_profiles() -> list[LLMProfile]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM llm_profiles ORDER BY id")
            return [_row_to_profile(r) for r in cur.fetchall()]
    except Exception:  # noqa: BLE001
        return []


def get_profile(profile_id: int) -> LLMProfile | None:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM llm_profiles WHERE id=%s", (int(profile_id),))
            row = cur.fetchone()
        return _row_to_profile(row) if row else None
    except Exception:  # noqa: BLE001
        return None


def get_default() -> LLMProfile | None:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM llm_profiles WHERE is_default AND enabled ORDER BY id LIMIT 1")
            row = cur.fetchone()
        return _row_to_profile(row) if row else None
    except Exception:  # noqa: BLE001
        return None


def bound_agents(profile_id: int) -> list[str]:
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT name FROM agent_configs WHERE llm_profile_id=%s ORDER BY name", (int(profile_id),))
            return [r[0] for r in cur.fetchall()]
    except Exception:  # noqa: BLE001
        return []


def create_profile(data: dict, actor: str = "system") -> LLMProfile | None:
    if not data.get("name"):
        raise ValueError("name 必填")
    err = _validate(data)
    if err:
        raise ValueError(err)
    payload = {k: data[k] for k in _FIELDS if k in data}
    if not payload.get("protocol"):
        payload["protocol"] = "openai-compatible"
    if not payload.get("provider"):
        payload["provider"] = "openai-compatible"
    if payload.get("enabled") is False:
        payload["is_default"] = False
    for k in ("capabilities", "extra_headers", "model_catalog", "model_protocols", "quota_windows"):
        payload.setdefault(k, {} if k not in ("model_catalog", "quota_windows") else [])
    cipher = encrypt_secret(str(data.get("api_key") or ""))
    cols = list(payload) + ["api_key_cipher"]
    vals = [_jsonify(k, v) for k, v in payload.items()] + [cipher]
    placeholders = ",".join(["%s"] * len(cols))
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            if payload.get("is_default"):
                cur.execute("UPDATE llm_profiles SET is_default=FALSE WHERE is_default")
            cur.execute(
                f"INSERT INTO llm_profiles ({','.join(cols)}) VALUES ({placeholders}) RETURNING *",
                vals,
            )
            profile = _row_to_profile(cur.fetchone())
            conn.commit()
        audit_write(actor, "create", "llm_profile", str(profile.id), None, to_public(profile))
        return profile
    except Exception:  # noqa: BLE001
        return None


def update_profile(profile_id: int, patch: dict, actor: str = "system") -> LLMProfile | None:
    before = get_profile(profile_id)
    if before is None:
        return None
    payload = {k: patch[k] for k in _FIELDS if k in patch}
    if payload.get("enabled") is False:
        payload["is_default"] = False
    err = _validate({**{k: getattr(before, k) for k in _FIELDS}, **payload})
    if err:
        raise ValueError(err)
    if payload.get("fallback_profile_id") == profile_id:
        raise ValueError("fallback 不能指向自身")
    sets: list[str] = []
    vals: list[Any] = []
    for k, v in payload.items():
        sets.append(f"{k}=%s")
        vals.append(_jsonify(k, v))
    if patch.get("api_key"):
        sets.append("api_key_cipher=%s")
        vals.append(encrypt_secret(str(patch["api_key"])))
    if not sets:
        return before
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            if payload.get("is_default"):
                cur.execute("UPDATE llm_profiles SET is_default=FALSE WHERE is_default AND id<>%s", (profile_id,))
            if patch.get("enabled") is False and "is_default" not in payload:
                sets.append("is_default=FALSE")
            sets.append("updated_at=now()")
            vals.append(profile_id)
            cur.execute(f"UPDATE llm_profiles SET {', '.join(sets)} WHERE id=%s RETURNING *", vals)
            profile = _row_to_profile(cur.fetchone())
            conn.commit()
        audit_write(actor, "update", "llm_profile", str(profile_id), to_public(before), to_public(profile))
        return profile
    except Exception:  # noqa: BLE001
        return None


def delete_profile(profile_id: int, actor: str = "system") -> str:
    """返回 'ok' | 'not_found' | 'bound' | 'error'。"""
    profile = get_profile(profile_id)
    if profile is None:
        return "not_found"
    if bound_agents(profile_id):
        return "bound"
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM llm_profiles WHERE id=%s", (int(profile_id),))
            conn.commit()
        audit_write(actor, "delete", "llm_profile", str(profile_id), to_public(profile), None)
        return "ok"
    except Exception:  # noqa: BLE001
        return "error"


def set_default(profile_id: int, actor: str = "system") -> LLMProfile | None:
    profile = get_profile(profile_id)
    if profile is None or not profile.enabled:
        return None
    return update_profile(profile_id, {"is_default": True}, actor=actor)


def resolve_profile(agent: str) -> tuple[LLMProfile | None, str]:
    """解析顺序：Agent 绑定 → fallback → 默认 → (None,'none')。"""
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT llm_profile_id FROM agent_configs WHERE name=%s", (agent,))
            row = cur.fetchone()
        bound_id = row[0] if row else None
    except Exception:  # noqa: BLE001
        bound_id = None
    if bound_id:
        bound = get_profile(int(bound_id))
        if bound and bound.enabled:
            return bound, "agent"
        if bound and bound.fallback_profile_id:
            fb = get_profile(int(bound.fallback_profile_id))
            if fb and fb.enabled:
                return fb, "fallback"
    default = get_default()
    if default:
        return default, "default"
    return None, "none"


def client_kwargs(profile: LLMProfile, session_id: str | None = None) -> dict:
    from codesentry.security.secrets import decrypt_secret

    headers = {
        str(k): str(v).replace("${session_id}", session_id or "")
        for k, v in (profile.extra_headers or {}).items()
    }
    return {
        "base_url": profile.base_url,
        "api_key": decrypt_secret(profile.api_key_cipher),
        "fast_model": profile.fast_model,
        "deep_model": profile.deep_model,
        "temperature": profile.temperature,
        "protocol": profile.protocol,
        "extra_headers": headers,
        "timeout_s": profile.timeout_s,
        "max_tokens": profile.max_tokens,
        "model_prefix_policy": profile.model_prefix_policy,
        "model_protocols": profile.model_protocols or {},
        "input_price_per_1k": profile.input_price_per_1k,
        "output_price_per_1k": profile.output_price_per_1k,
        "billing_mode": profile.billing_mode,
        "profile_id": profile.id,
    }


def probe_models(profile_id: int, limit: int = 5) -> dict:
    from codesentry.agents.llm import LLMClient, LLMError

    profile = get_profile(profile_id)
    if profile is None:
        return {"ok": False, "error": "not_found"}
    try:
        base_kwargs = client_kwargs(profile, session_id=f"probe-{profile_id}")
        base_kwargs.update({"record_usage": False, "retries": 1, "timeout_s": 15})
        client = LLMClient(**base_kwargs)
        models = client.probe_models()
        protocols: dict[str, str] = {}
        for model in models[: max(1, min(int(limit), 20))]:
            probe = LLMClient(**base_kwargs)
            probe.fast_model = model
            probe.model_protocols = {}
            for proto in ("openai-compatible", "anthropic-compatible"):
                probe.protocol = proto
                try:
                    probe.complete("You are a probe.", "OK", model_role="fast")
                    protocols[model] = proto
                    break
                except LLMError:
                    continue
            else:
                protocols[model] = "unavailable"
        merged = dict(profile.model_protocols or {})
        merged.update({k: v for k, v in protocols.items() if v != "unavailable"})
        update_profile(
            profile_id,
            {
                "model_catalog": models,
                "model_protocols": merged,
                "capabilities": {**(profile.capabilities or {}), "probed": True},
            },
            actor="api",
        )
        return {"ok": True, "models": models, "protocols": protocols,
                "capabilities": profile.capabilities or {}}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}
