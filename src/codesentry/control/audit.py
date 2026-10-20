"""配置变更审计（M6.1）：before/after 落库，密钥字段脱敏。"""

from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any

from codesentry.security.secrets import redact_mapping

_actor_ctx: ContextVar[str] = ContextVar("audit_actor", default="")


def set_actor(actor: str) -> None:
    _actor_ctx.set(actor or "")


def audit_write(
    actor: str,
    action: str,
    target_type: str,
    target_id: str,
    before: Any = None,
    after: Any = None,
) -> bool:
    """写一条审计；无库/失败返回 False，不阻塞业务。"""
    if actor in ("", "api", "system") and _actor_ctx.get():
        actor = _actor_ctx.get()
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO config_audit (actor, action, target_type, target_id, before, after)"
                " VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    actor or "system",
                    action,
                    target_type,
                    str(target_id),
                    json.dumps(redact_mapping(before), ensure_ascii=False) if before is not None else None,
                    json.dumps(redact_mapping(after), ensure_ascii=False) if after is not None else None,
                ),
            )
            conn.commit()
        return True
    except Exception:  # noqa: BLE001 - 审计失败不阻塞业务
        return False


def list_audit(
    limit: int = 100,
    target_type: str | None = None,
    actor: str | None = None,
) -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        clauses: list[str] = []
        params: list[object] = []
        if target_type:
            clauses.append("target_type=%s")
            params.append(target_type)
        if actor:
            clauses.append("actor=%s")
            params.append(actor)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, actor, action, target_type, target_id, before, after, created_at"
                f" FROM config_audit{where} ORDER BY id DESC LIMIT %s",
                params,
            )
            rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "actor": r[1],
                "action": r[2],
                "target_type": r[3],
                "target_id": r[4],
                "before": r[5],
                "after": r[6],
                "created_at": str(r[7]),
            }
            for r in rows
        ]
    except Exception:  # noqa: BLE001
        return []
