"""psycopg 连接池（agent.md §8；search_path 固定业务 schema）。"""

from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None or _pool.closed:
        from codesentry.config import get_settings

        _pool = ConnectionPool(
            get_settings().database_url,
            min_size=1,
            max_size=8,
            open=True,
            kwargs={"options": "-c search_path=codesentry,public"},
        )
    return _pool


@contextmanager
def get_conn():
    pool = _get_pool()
    with pool.connection() as conn:
        yield conn


def close_pool() -> None:
    global _pool
    if _pool is not None and not _pool.closed:
        _pool.close()
    _pool = None
