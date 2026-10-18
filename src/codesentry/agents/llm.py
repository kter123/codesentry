"""OpenAI 兼容 LLM 客户端（agent.md D5/D14/§10）。温度 0；指数退避重试 3 次后抛错。"""

import contextvars
import os
import time


class LLMError(Exception):
    pass


# contextvar：本节点内 LLM tokens 增量（graph _wrap 节点结束时读取并归零回流 BudgetGuard）
_node_tokens: contextvars.ContextVar[int] = contextvars.ContextVar("node_tokens", default=0)


def current_tokens_delta() -> int:
    """返回并清零本节点 tokens 增量（NFR-2 token 回流）。"""
    val = _node_tokens.get()
    _node_tokens.set(0)
    return val


class LLMClient:
    def __init__(self, base_url: str, api_key: str, fast_model: str, deep_model: str, temperature: float = 0.0, retries: int = 3) -> None:
        if not base_url or not fast_model or not deep_model:
            raise LLMError(
                "LLM 未配置：需 CODESENTRY_MODEL_BASE_URL / CODESENTRY_FAST_MODEL / CODESENTRY_DEEP_MODEL"
            )
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.fast_model = fast_model
        self.deep_model = deep_model
        self.temperature = temperature
        self.retries = retries
        from openai import OpenAI

        self._client = OpenAI(base_url=self.base_url, api_key=api_key or "not-needed")
        self.tokens_used = 0

    @classmethod
    def from_config(cls) -> "LLMClient":
        from codesentry.config import get_settings

        s = get_settings()
        return cls(
            base_url=s.model_base_url,
            api_key=s.model_api_key,
            fast_model=s.fast_model,
            deep_model=s.deep_model,
            temperature=s.temperature,
        )

    def complete(self, system: str, user: str, model_role: str = "deep") -> str:
        model = self.deep_model if model_role == "deep" else self.fast_model
        delay = 1.0
        last_err: Exception | None = None
        for attempt in range(self.retries):
            try:
                resp = self._client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    temperature=self.temperature,
                )
                usage = getattr(resp, "usage", None)
                if usage is not None:
                    used = getattr(usage, "total_tokens", 0) or 0
                    self.tokens_used += used
                    _node_tokens.set(_node_tokens.get() + used)
                return resp.choices[0].message.content or ""
            except Exception as e:  # noqa: BLE001 - 上游网络异常必须退避重试
                last_err = e
                if attempt < self.retries - 1:
                    time.sleep(delay)
                    delay *= 2
        raise LLMError(f"LLM {self.retries} 次重试后仍失败: {last_err}") from last_err
