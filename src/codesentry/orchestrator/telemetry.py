"""节点遥测直写 node_runs（agent.md §7.3/D22：不引入消息队列）。"""

import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from codesentry.db.pool import get_conn


@dataclass
class NodeRun:
    tokens: int = 0
    tool_calls: int = 0


@contextmanager
def node_run(scan_id: int, node: str, tokens: int = 0, tool_calls: int = 0,
             status_override: str | None = None):
    """上下文管理器：进入记 start，退出算 duration 并落 node_runs。异常也落 error。"""
    started = time.monotonic()
    start_at = datetime.now(UTC)
    status = status_override or "ok"
    error = ""
    run = NodeRun(tokens=tokens, tool_calls=tool_calls)
    agent_key = f"{node}:{start_at.isoformat()}"
    publish = None
    try:
        from codesentry.orchestrator.events import publish_event, upsert_agent_node

        publish_event(scan_id, "node.start", agent=node, phase=node,
                      payload={"node": node, "started_at": start_at.isoformat()})
        upsert_agent_node(scan_id, agent_key, name=node, phase=node, status="running")
        publish = publish_event
    except Exception:  # noqa: BLE001
        publish = None
    try:
        yield run
    except Exception as e:
        status = "failed"
        error = str(e)[:500]
        raise
    finally:
        if status_override and status != "failed":
            status = status_override
        duration_ms = int((time.monotonic() - started) * 1000)
        ended_at = datetime.now(UTC)
        try:
            with get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO node_runs
                        (scan_id, node, started_at, ended_at, duration_ms, tokens, tool_calls, status, error)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (scan_id, node, start_at, ended_at, duration_ms,
                     run.tokens or 0, run.tool_calls or 0, status, error),
                )
                conn.commit()
        except Exception:  # noqa: BLE001, S110 - 遥测写入失败不阻塞主流程（扫描结果另落表）
            pass
        if publish is not None:
            try:
                from codesentry.orchestrator.events import upsert_agent_node

                publish(scan_id, "node.end", agent=node, phase=node, payload={
                    "node": node, "status": status, "duration_ms": duration_ms,
                    "tokens": run.tokens or 0, "error": error,
                })
                upsert_agent_node(scan_id, agent_key, name=node, phase=node,
                                  status=status, tokens=run.tokens or 0,
                                  tool_calls=run.tool_calls or 0,
                                  summary=error or f"{duration_ms}ms")
            except Exception:  # noqa: BLE001, S110
                pass
