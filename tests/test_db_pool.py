import os

import pytest

from codesentry.db.pool import close_pool, get_conn


@pytest.fixture(autouse=True)
def _close_after():
    yield
    close_pool()


def test_pool_connect_and_query():
    os.environ.setdefault("CODESENTRY_DATABASE_URL", "postgresql://codesentry:devtest@127.0.0.1:5432/codesentry")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone()[0] == 1


def test_pool_search_path():
    os.environ.setdefault("CODESENTRY_DATABASE_URL", "postgresql://codesentry:devtest@127.0.0.1:5432/codesentry")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SHOW search_path")
            assert "codesentry" in cur.fetchone()[0]
