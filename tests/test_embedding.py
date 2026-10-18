import os

import pytest

from codesentry.rag.embedding import EmbeddingClient


def test_client_requires_config(monkeypatch):
    for k in list(os.environ):
        if k.startswith("CODESENTRY_"):
            monkeypatch.delenv(k)
    with pytest.raises(RuntimeError, match="embedding"):
        EmbeddingClient.from_config()


def test_client_local_bge_m3(monkeypatch):
    monkeypatch.setenv("CODESENTRY_EMBEDDING_MODEL", "bge-m3")
    monkeypatch.setenv("CODESENTRY_MODEL_BASE_URL", "http://127.0.0.1:11434/v1")
    c = EmbeddingClient.from_config()
    assert c.is_local


def test_client_remote_channel(monkeypatch):
    monkeypatch.setenv("CODESENTRY_EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.setenv("CODESENTRY_MODEL_BASE_URL", "https://api.example.com/v1")
    c = EmbeddingClient.from_config()
    assert not c.is_local
