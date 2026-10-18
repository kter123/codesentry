import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parent.parent / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

# 每个测试后关闭全局连接池——避免跨测试共享 pool 的状态污染（合跑错误根因）
import pytest


@pytest.fixture(autouse=True)
def _close_pool_per_test():
    yield
    try:
        from codesentry.db import pool as db_pool

        db_pool.close_pool()
    except Exception:  # noqa: BLE001, S110
        pass
