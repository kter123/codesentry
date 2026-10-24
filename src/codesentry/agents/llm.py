"""LLM 客户端（M6.1）：Profile 构造、OpenAI/Anthropic 双协议、用量与成本。

保留 M3 的 `LLMClient(base_url, api_key, fast_model, deep_model)` 与 `from_config()` 签名，
新增参数全部可选。温度 0；可重试错误指数退避，配置/协议错误不盲目重试。
"""

from __future__ import annotations

import contextvars
import re
import time
from typing import Any

import httpx

_OPENAI = "openai-compatible"
_ANTHROPIC = "anthropic-compatible"
_PROTOCOLS = {_OPENAI, _ANTHROPIC}

# contextvar：本节点内 LLM tokens 增量（graph _wrap 节点结束时读取并归零回流 BudgetGuard）
_node_tokens: contextvars.ContextVar[int] = contextvars.ContextVar("node_tokens", default=0)
_node_cost: contextvars.ContextVar[float] = contextvars.ContextVar("node_cost", default=0.0)


class LLMError(Exception):
    kind = "llm_error"


class LLMConfigError(LLMError):
    kind = "config"


class LLMProtocolError(LLMError):
    kind = "protocol"


class LLMUnavailableError(LLMError):
    kind = "unavailable"


def current_tokens_delta() -> int:
    """返回并清零本节点 tokens 增量（NFR-2 token 回流）。"""
    val = _node_tokens.get()
    _node_tokens.set(0)
    return val


def current_cost_delta() -> float:
    val = _node_cost.get()
    _node_cost.set(0.0)
    return val


def _error_text(exc: Exception) -> str:
    return str(exc)


_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{6,}|Bearer\s+[A-Za-z0-9._\-]{6,})")


def _mask_secrets(text: str) -> str:
    return _SECRET_RE.sub(lambda m: m.group(1)[:3] + "***", text)


def _classify(exc: Exception) -> str:
    text = _error_text(exc).lower()
    if "missingsessionid" in text or "missing x-opencode-session" in text:
        return "missing_session"
    if "modelprotocolunsupported" in text or "does not support this protocol" in text:
        return "protocol"
    if "model is unavailable" in text:
        return "unavailable"
    status = getattr(exc, "status_code", None)
    if status is None:
        import re

        m = re.search(r"http (\d{3})", text)
        status = int(m.group(1)) if m else None
    if status in (401, 403, 404):
        return "config"
    if status == 429 or (status is not None and 500 <= status < 600):
        return "retryable"
    if status is not None and 400 <= status < 500:
        return "config"
    return "retryable"


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        fast_model: str,
        deep_model: str,
        temperature: float = 0.0,
        retries: int = 3,
        *,
        protocol: str = _OPENAI,
        extra_headers: dict[str, str] | None = None,
        timeout_s: int = 60,
        max_tokens: int = 0,
        model_prefix_policy: str = "keep",
        model_protocols: dict[str, str] | None = None,
        input_price_per_1k: float = 0.0,
        output_price_per_1k: float = 0.0,
        billing_mode: str = "metered",
        profile_id: int | None = None,
        agent: str = "default",
        scan_id: int = 0,
        transport: httpx.BaseTransport | None = None,
        record_usage: bool = True,
    ) -> None:
        if not base_url or not fast_model or not deep_model:
            raise LLMError(
                "LLM 未配置：需 CODESENTRY_MODEL_BASE_URL / CODESENTRY_FAST_MODEL / CODESENTRY_DEEP_MODEL"
            )
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.fast_model = fast_model
        self.deep_model = deep_model
        self.temperature = temperature
        self.retries = max(1, int(retries))
        self.protocol = protocol if protocol in _PROTOCOLS else _OPENAI
        self.extra_headers = dict(extra_headers or {})
        self.timeout_s = max(1, int(timeout_s or 60))
        self.max_tokens = max(0, int(max_tokens or 0))
        self.model_prefix_policy = model_prefix_policy or "keep"
        self.model_protocols = dict(model_protocols or {})
        self.input_price_per_1k = float(input_price_per_1k or 0.0)
        self.output_price_per_1k = float(output_price_per_1k or 0.0)
        self.billing_mode = billing_mode or "metered"
        self.profile_id = profile_id
        self.agent = agent
        self.scan_id = int(scan_id or 0)
        self.tokens_used = 0
        self.last_meta: dict[str, Any] = {}
        self._fallback: LLMClient | None = None
        self._pool: list[LLMClient] = []
        self._transport = transport
        self.record_usage = record_usage

        from openai import OpenAI

        self._client = OpenAI(
            base_url=self.base_url,
            api_key=api_key or "not-needed",
            timeout=self.timeout_s,
            default_headers=self.extra_headers or None,
        )

    # ---- 构造 ----
    @classmethod
    def from_config(cls, *, agent: str = "default", scan_id: int = 0) -> LLMClient:
        from codesentry.config import get_settings

        s = get_settings()
        return cls(
            base_url=s.model_base_url,
            api_key=s.model_api_key,
            fast_model=s.fast_model,
            deep_model=s.deep_model,
            temperature=s.temperature,
            agent=agent,
            scan_id=scan_id,
        )

    @classmethod
    def from_profile(
        cls,
        profile: Any,
        *,
        session_id: str | None = None,
        agent: str = "default",
        scan_id: int = 0,
        timeout_s: int | None = None,
        temperature: float | None = None,
    ) -> LLMClient:
        from codesentry.control.profiles import client_kwargs

        kwargs = client_kwargs(profile, session_id=session_id)
        if timeout_s is not None:
            kwargs["timeout_s"] = int(timeout_s)
        if temperature is not None:
            kwargs["temperature"] = float(temperature)
        return cls(agent=agent, scan_id=scan_id, **kwargs)

    @classmethod
    def for_agent(
        cls,
        agent: str,
        *,
        role: str | None = None,
        profile: Any | None = None,
        session_id: str | None = None,
        scan_id: int = 0,
        timeout_s: int | None = None,
        temperature: float | None = None,
    ) -> LLMClient:
        """解析 Agent 绑定 → fallback → 默认 → .env；全部不可用抛 LLMError。"""
        if profile is None:
            try:
                from codesentry.control.profiles import resolve_profile

                profile, _source = resolve_profile(agent)
            except Exception:  # noqa: BLE001 - 无库回退 .env
                profile = None
        if profile is not None:
            try:
                client = cls.from_profile(
                    profile,
                    session_id=session_id or f"scan-{scan_id}-{agent}-{profile.id}",
                    agent=agent,
                    scan_id=scan_id,
                    timeout_s=timeout_s,
                    temperature=temperature,
                )
                fid = getattr(profile, "fallback_profile_id", None)
                if fid is not None:
                    from codesentry.control.profiles import get_profile

                    fb = get_profile(int(fid))
                    if fb is not None and fb.enabled and fb.id != profile.id:
                        try:
                            client._pool.append(cls.from_profile(
                                fb,
                                session_id=session_id or f"scan-{scan_id}-{agent}-{fb.id}",
                                agent=agent,
                                scan_id=scan_id,
                                timeout_s=timeout_s,
                                temperature=temperature,
                            ))
                        except Exception:  # noqa: BLE001, S110 - 单个备用不可用不阻塞
                            pass
                try:
                    from codesentry.control.llm_pool import chain_profiles

                    for candidate in chain_profiles(profile.id)[1:]:
                        if any(c.profile_id == candidate.id for c in [client, *client._pool]):
                            continue
                        try:
                            client._pool.append(cls.from_profile(
                                candidate,
                                session_id=session_id or f"scan-{scan_id}-{agent}-{candidate.id}",
                                agent=agent,
                                scan_id=scan_id,
                                timeout_s=timeout_s,
                                temperature=temperature,
                            ))
                        except Exception:  # noqa: BLE001, S112 - 单个备用不可用则跳过
                            continue
                except Exception:  # noqa: BLE001, S110
                    pass
                return client
            except Exception as exc:  # noqa: BLE001 - Profile 不可用时继续尝试 .env
                try:
                    return cls.from_config()
                except Exception as fc_exc:
                    raise exc from fc_exc
        return cls.from_config()

    # ---- 模型/协议 ----
    def _normalize_model(self, model: str) -> str:
        if self.model_prefix_policy == "strip" and "/" in model:
            model = model.rsplit("/", 1)[-1]
        return model

    def _protocol_for(self, model: str) -> str:
        proto = self.model_protocols.get(model)
        if proto in _PROTOCOLS:
            return proto
        return self.protocol

    # ---- 调用 ----
    def complete(self, system: str, user: str, model_role: str = "deep") -> str:
        from codesentry.control import llm_pool

        errors: list[Exception] = []
        for client in [self, *self._pool]:
            profile_id = getattr(client, "profile_id", None)
            if profile_id and llm_pool.is_open(int(profile_id)):
                continue
            try:
                text = client._complete_inner(system, user, model_role=model_role)
                if profile_id:
                    llm_pool.record_success(int(profile_id))
                return text
            except LLMError as exc:
                if profile_id:
                    llm_pool.record_failure(int(profile_id), str(exc))
                errors.append(exc)
        if self._fallback is not None:
            return self._fallback.complete(system, user, model_role=model_role)
        if errors:
            raise errors[-1]
        raise LLMError("所有 LLM 配置均不可用（熔断冷却中）")

    def _complete_inner(self, system: str, user: str, model_role: str = "deep") -> str:
        model = self._normalize_model(self.deep_model if model_role == "deep" else self.fast_model)
        protocol = self._protocol_for(model)
        tried: set[str] = set()
        delay = 1.0
        last_err: Exception | None = None

        for attempt in range(self.retries):
            tried.add(protocol)
            started = time.monotonic()
            try:
                if protocol == _ANTHROPIC:
                    text, reasoning, pt, ct = self._call_anthropic(model, system, user)
                else:
                    text, reasoning, pt, ct = self._call_openai(model, system, user)
                latency_ms = int((time.monotonic() - started) * 1000)
                self._record(model, pt, ct, latency_ms, ok=True)
                self._log_call(model, system, user, text, pt, ct, latency_ms, ok=True)
                self.last_meta = {
                    "model": model,
                    "protocol": protocol,
                    "prompt_tokens": pt,
                    "completion_tokens": ct,
                    "cost_usd": self._cost(pt, ct),
                    "latency_ms": latency_ms,
                    "reasoning": reasoning or "",
                    "ok": True,
                }
                return text
            except Exception as exc:
                last_err = exc
                kind = _classify(exc)
                latency_ms = int((time.monotonic() - started) * 1000)
                if kind == "missing_session":
                    self._record(model, 0, 0, latency_ms, ok=False, error="missing_session")
                    self._log_call(model, system, user, "", 0, 0, latency_ms, False, "missing_session")
                    raise LLMConfigError(
                        "Provider 要求 x-opencode-session 请求头，请检查 Profile 的 extra_headers"
                    ) from exc
                if kind == "config":
                    self._record(model, 0, 0, latency_ms, ok=False,
                                 error=f"config: {_error_text(exc)[:200]}")
                    self._log_call(model, system, user, "", 0, 0, latency_ms, False,
                                   f"config: {_error_text(exc)[:200]}")
                    raise LLMConfigError(f"Provider 配置/请求错误：{_error_text(exc)[:200]}") from exc
                if kind == "protocol":
                    alt = _ANTHROPIC if protocol == _OPENAI else _OPENAI
                    if alt not in tried:
                        protocol = alt
                        continue
                    self._record(model, 0, 0, latency_ms, ok=False,
                                 error=f"protocol: {_error_text(exc)[:200]}")
                    self._log_call(model, system, user, "", 0, 0, latency_ms, False,
                                   f"protocol: {_error_text(exc)[:200]}")
                    raise LLMProtocolError(f"模型 {model} 不支持当前协议：{_error_text(exc)[:200]}") from exc
                if kind == "unavailable":
                    self._record(model, 0, 0, latency_ms, ok=False,
                                 error=f"unavailable: {_error_text(exc)[:200]}")
                    self._log_call(model, system, user, "", 0, 0, latency_ms, False,
                                   f"unavailable: {_error_text(exc)[:200]}")
                    raise LLMUnavailableError(f"模型 {model} 当前不可用：{_error_text(exc)[:200]}") from exc
                if attempt < self.retries - 1:
                    time.sleep(delay)
                    delay *= 2

        self._record(model, 0, 0, 0, ok=False,
                     error=f"retry_exhausted: {_error_text(last_err or Exception('unknown'))[:200]}")
        self._log_call(model, system, user, "", 0, 0, 0, False,
                       f"retry_exhausted: {_error_text(last_err or Exception('unknown'))[:200]}")
        raise LLMError(f"LLM {self.retries} 次重试后仍失败: {last_err}") from last_err

    def _call_openai(self, model: str, system: str, user: str) -> tuple[str, str, int, int]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
        }
        if self.max_tokens:
            kwargs["max_tokens"] = self.max_tokens
        resp = self._client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        content = getattr(msg, "content", None) or ""
        reasoning = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None) or ""
        usage = getattr(resp, "usage", None)
        pt = int(getattr(usage, "prompt_tokens", 0) or 0)
        ct = int(getattr(usage, "completion_tokens", 0) or 0)
        if not content and reasoning:
            content = str(reasoning)
        return str(content), str(reasoning), pt, ct

    def _call_anthropic(self, model: str, system: str, user: str) -> tuple[str, str, int, int]:
        headers = {
            "x-api-key": self.api_key or "not-needed",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            **self.extra_headers,
        }
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": self.max_tokens or 4096,
            "temperature": self.temperature,
            "messages": [{"role": "user", "content": user}],
        }
        if system:
            payload["system"] = system
        with httpx.Client(timeout=self.timeout_s, transport=self._transport) as client:
            resp = client.post(f"{self.base_url}/messages", headers=headers, json=payload)
        if resp.status_code >= 400:
            raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        text = "".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        )
        thinking = "".join(
            b.get("thinking", "") for b in data.get("content", []) if b.get("type") == "thinking"
        )
        usage = data.get("usage") or {}
        return (
            text or thinking,
            thinking,
            int(usage.get("input_tokens", 0) or 0),
            int(usage.get("output_tokens", 0) or 0),
        )

    # ---- 用量 ----
    def _cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        if self.billing_mode in ("subscription", "local"):
            return 0.0
        return (
            prompt_tokens / 1000.0 * self.input_price_per_1k
            + completion_tokens / 1000.0 * self.output_price_per_1k
        )

    def _record(self, model: str, pt: int, ct: int, latency_ms: int, *, ok: bool, error: str = "") -> None:
        used = pt + ct
        cost = self._cost(pt, ct)
        self.tokens_used += used
        _node_tokens.set(_node_tokens.get() + used)
        _node_cost.set(_node_cost.get() + cost)
        if not self.record_usage:
            return
        try:
            from codesentry.control.usage import record_usage

            record_usage(
                scan_id=self.scan_id or None,
                agent=self.agent,
                profile_id=self.profile_id,
                model=model,
                prompt_tokens=pt,
                completion_tokens=ct,
                cost_usd=cost,
                latency_ms=latency_ms,
                ok=ok,
                error=error,
            )
        except Exception:  # noqa: BLE001, S110 - 台账失败不阻塞
            pass

    def _log_call(self, model: str, system: str, user: str, response: str, pt: int, ct: int,
                  latency_ms: int, ok: bool, error: str = "") -> None:
        if not self.record_usage:
            return
        try:
            from codesentry.config import get_settings

            if not get_settings().record_llm_calls:
                return
            from codesentry.db.pool import get_conn

            request = f"system: {system[:800]}\nuser: {user[:1200]}"
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO llm_calls (scan_id, agent, profile_id, model, request_preview,"
                    " response_preview, prompt_tokens, completion_tokens, cost_usd, latency_ms,"
                    " ok, error) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (self.scan_id or None, self.agent, self.profile_id,
                     model, _mask_secrets(request),
                     _mask_secrets(response[:1200]), pt, ct, self._cost(pt, ct),
                     latency_ms, ok, error[:300]),
                )
                conn.commit()
        except Exception:  # noqa: BLE001, S110 - 原始记录失败不阻塞
            pass

    def probe_models(self) -> list[str]:
        """拉取 Provider 模型列表；失败返回空列表。"""
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.update(self.extra_headers)
        try:
            with httpx.Client(timeout=self.timeout_s, transport=self._transport) as client:
                resp = client.get(f"{self.base_url}/models", headers=headers)
            if resp.status_code >= 400:
                return []
            data = resp.json()
            return [str(m.get("id")) for m in data.get("data", []) if m.get("id")]
        except Exception:  # noqa: BLE001
            return []
