"""PostgresSaver checkpoint（§7.3；langgraph schema）。"""

import os
from contextlib import contextmanager
from functools import lru_cache


@lru_cache(maxsize=1)
def _get_saver():
    from langgraph.checkpoint.postgres import PostgresSaver

    from codesentry.config import get_settings

    url = get_settings().database_url
    saver = PostgresSaver.from_conn_string(url)
    saver.setup()
    return saver


@contextmanager
def checkpointer():
    saver = _get_saver()
    try:
        yield saver
    finally:
        pass  # saver 长连接由 pool 管理，不逐次关闭
