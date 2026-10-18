"""Embedding 双通道客户端（agent.md D10）。

两类通道都走 OpenAI 兼容 `/v1/embeddings`：
- 远程 OpenAI 兼容接口（用户自配 base_url）
- 本地 bge-m3（挂载盘模型，经 vLLM/Ollama 等以同协议暴露，base_url 指向 127.0.0.1）

同维度入库；`is_local` 用于数据本地化策略判断。
"""

import os

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class EmbeddingClient:
    def __init__(self, base_url: str, model: str, api_key: str = "") -> None:
        if not model or not base_url:
            raise RuntimeError(
                "embedding channel 未配置：需 CODESENTRY_EMBEDDING_BASE_URL + CODESENTRY_EMBEDDING_MODEL"
                "（本地 bge-m3 经 ollama 暴露：http://127.0.0.1:11434/v1）"
            )
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        from openai import OpenAI

        self._client = OpenAI(base_url=self.base_url, api_key=api_key or "not-needed")

    @classmethod
    def from_config(cls) -> "EmbeddingClient":
        from codesentry.config import get_settings

        s = get_settings()
        return cls(
            base_url=s.embedding_base_url or s.model_base_url,
            model=s.embedding_model,
            api_key=s.embedding_api_key or "",
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
