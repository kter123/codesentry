import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parent.parent / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

# 每个测试后关闭全局连接池——避免跨测试共享 pool 的状态污染（合跑错误根因）
import pytest


@pytest.fixture(scope="session", autouse=True)
def _ensure_schema_once():
    try:
        from codesentry.control.bootstrap import ensure_control_schema

        ensure_control_schema(force=True)
    except Exception:  # noqa: BLE001, S110
        pass


@pytest.fixture(autouse=True)
def _close_pool_per_test():
    yield
    try:
        from codesentry.db import pool as db_pool

        db_pool.close_pool()
    except Exception:  # noqa: BLE001, S110
        pass


@pytest.fixture(autouse=True)
def _no_live_llm(request, monkeypatch):
    """默认封空 LLM 配置，避免单测/集成测试调用真实 API；live 标记除外。"""
    if request.node.get_closest_marker("live"):
        return
    for key in (
        "CODESENTRY_MODEL_BASE_URL",
        "CODESENTRY_MODEL_API_KEY",
        "CODESENTRY_FAST_MODEL",
        "CODESENTRY_DEEP_MODEL",
    ):
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("CODESENTRY_DEPLOY_ENABLED", "false")
    monkeypatch.setenv("CODESENTRY_DEPLOY_KEEP", "false")
    monkeypatch.setenv("CODESENTRY_LLM_ENABLED", "false")
