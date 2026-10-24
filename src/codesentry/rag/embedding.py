"""Embedding 双通道客户端（agent.md D10）。

两类通道都走 OpenAI 兼容 `/v1/embeddings`：
- 远程 OpenAI 兼容接口（用户自配 base_url）
- 本地 bge-m3（挂载盘模型，经 vLLM/Ollama 等以同协议暴露，base_url 指向 127.0.0.1）

同维度入库；`is_local` 用于数据本地化策略判断。
"""


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_DISABLED_UNTIL = 0.0


class EmbeddingClient:
    def __init__(self, base_url: str, model: str, api_key: str = "",
                 timeout_s: float = 60.0) -> None:
        if not model or not base_url:
            raise RuntimeError(
                "embedding channel 未配置：需 CODESENTRY_EMBEDDING_BASE_URL + CODESENTRY_EMBEDDING_MODEL"
                "（本地 bge-m3 经 ollama 暴露：http://127.0.0.1:11434/v1）"
            )
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        from openai import OpenAI

        # 检索是可选增强：不可达时必须快速降级到 FTS，不能拖住扫描节点
        self._client = OpenAI(
            base_url=self.base_url, api_key=api_key or "not-needed",
            timeout=float(timeout_s or 60.0), max_retries=0,
        )

    @classmethod
    def from_config(cls) -> "EmbeddingClient":
        from codesentry.config import get_settings

        s = get_settings()
        return cls(
            base_url=s.embedding_base_url or s.model_base_url,
            model=s.embedding_model,
            api_key=s.embedding_api_key or "",
            timeout_s=float(getattr(s, "embedding_timeout_s", 60.0) or 60.0),
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


def embed_texts(texts: list[str]) -> list[list[float] | None]:
    """批量取查询向量；未配置/失败时返回等长 None（调用方降级 FTS）。"""
    global _DISABLED_UNTIL
    if not texts:
        return []
    import time

    if time.monotonic() < _DISABLED_UNTIL:
        return [None] * len(texts)
    try:
        client = EmbeddingClient.from_config()
        vectors: list[list[float] | None] = []
        for i in range(0, len(texts), 64):
            vectors.extend(client.embed(texts[i : i + 64]))
        if len(vectors) != len(texts):
            return [None] * len(texts)
        return vectors
    except Exception:  # noqa: BLE001 - 检索降级为全文
        _DISABLED_UNTIL = time.monotonic() + 60
        return [None] * len(texts)
