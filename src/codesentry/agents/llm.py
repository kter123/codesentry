"""OpenAI 兼容 LLM 客户端（agent.md D5/D14/§10）。温度 0；指数退避重试 3 次后抛错。"""

import os
import time


class LLMError(Exception):
    pass


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
        return cls(
            base_url=os.environ.get("CODESENTRY_MODEL_BASE_URL", ""),
            api_key=os.environ.get("CODESENTRY_MODEL_API_KEY", ""),
            fast_model=os.environ.get("CODESENTRY_FAST_MODEL", ""),
            deep_model=os.environ.get("CODESENTRY_DEEP_MODEL", ""),
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
                    self.tokens_used += getattr(usage, "total_tokens", 0) or 0
                return resp.choices[0].message.content or ""
            except Exception as e:  # noqa: BLE001 - 上游网络异常必须退避重试
                last_err = e
                if attempt < self.retries - 1:
                    time.sleep(delay)
                    delay *= 2
        raise LLMError(f"LLM {self.retries} 次重试后仍失败: {last_err}") from last_err
