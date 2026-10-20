"""M6.1 schema 懒加载：控制面调用前确保新表存在。"""

from __future__ import annotations

import time

_ready = False
_failed_at: float | None = None


def ensure_control_schema(force: bool = False) -> bool:
    """幂等执行全量 DDL；失败返回 False（调用方降级，不抛）。"""
    global _ready, _failed_at
    if _ready and not force:
        return True
    if not force and _failed_at is not None and time.time() - _failed_at < 30:
        return False
    try:
        import psycopg

        from codesentry.config import get_settings
        from codesentry.db.ddl import render_full_ddl

        with psycopg.connect(get_settings().database_url, connect_timeout=3) as conn:
            conn.execute(render_full_ddl())
            conn.commit()
        _ready = True
        _failed_at = None
        return True
    except Exception:  # noqa: BLE001 - 无库时降级
        _failed_at = time.time()
        return False


def reset_cache() -> None:
    global _ready, _failed_at
    _ready = False
    _failed_at = None
