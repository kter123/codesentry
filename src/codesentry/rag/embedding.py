"""Embedding 双通道客户端（agent.md D10）。

两类通道都走 OpenAI 兼容 `/v1/embeddings`：
- 远程 OpenAI 兼容接口（用户自配 base_url）
- 本地 bge-m3（挂载盘模型，经 vLLM/Ollama 等以同协议暴露，base_url 指向 127.0.0.1）

同维度入库；`is_local` 用于数据本地化策略判断。
"""

import os
from typing import Protocol

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class _EmbeddingsApi(Protocol):
    def create(self, *, model: str, input, **kw): ...


class EmbeddingClient:
    def __init__(self, base_url: str, model: str, api_key: str = "") -> None:
        if not model or not base_url:
            raise RuntimeError(
                "embedding channel 未配置：需 CODESENTRY_EMBEDDING_MODEL 与 CODESENTRY_MODEL_BASE_URL"
                "（本地 bge-m3 也应经 OpenAI 兼容协议暴露，如 http://127.0.0.1:11434/v1）"
            )
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        from openai import OpenAI

        self._client = OpenAI(base_url=self.base_url, api_key=api_key or "not-needed")

    @classmethod
    def from_config(cls) -> "EmbeddingClient":
        return cls(
            base_url=os.environ.get("CODESENTRY_MODEL_BASE_URL", ""),
            model=os.environ.get("CODESENTRY_EMBEDDING_MODEL", ""),
            api_key=os.environ.get("CODESENTRY_MODEL_API_KEY", ""),
        )

    @property
    def is_local(self) -> bool:
        from urllib.parse import urlparse

        host = urlparse(self.base_url).hostname or ""
        return host in LOCAL_HOSTS

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = self._client.embeddings.create(model=self.model, input=texts)
        data = sorted(resp.data, key=lambda d: d.index)
        return [d.embedding for d in data]

    @property
    def dims(self) -> int:
        v = self.embed([""])[0]
        return len(v)
