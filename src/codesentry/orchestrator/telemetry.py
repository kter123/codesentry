"""节点遥测直写 node_runs（agent.md §7.3/D22：不引入消息队列）。"""

import time
from contextlib import contextmanager
from datetime import datetime, timezone

from codesentry.db.pool import get_conn


@contextmanager
def node_run(scan_id: int, node: str, tokens: int = 0, tool_calls: int = 0):
    """上下文管理器：进入记 start，退出算 duration 并落 node_runs。异常也落 error。"""
    started = time.monotonic()
    start_at = datetime.now(timezone.utc)
    status = "ok"
    error = ""
    try:
        yield
    except Exception as e:  # noqa: BLE001 - 遥测必须捕获以记录 error 状态，随后原样上抛
        status = "failed"
        error = str(e)[:500]
        raise
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        ended_at = datetime.now(timezone.utc)
        try:
            with get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO node_runs
                        (scan_id, node, started_at, ended_at, duration_ms, tokens, tool_calls, status, error)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (scan_id, node, start_at, ended_at, duration_ms,
                     tokens or 0, tool_calls or 0, status, error),
                )
                conn.commit()
        except Exception:  # noqa: BLE001, S110 - 遥测写入失败不阻塞主流程（扫描结果另落表）
            pass
