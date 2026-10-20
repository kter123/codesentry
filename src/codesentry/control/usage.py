"""LLM 用量与成本台账（M6.1）：每次调用落 llm_usage，支持聚合与配额。"""

from __future__ import annotations

from datetime import UTC, datetime

_GROUP_EXPR = {
    "profile": "profile_id",
    "agent": "agent",
    "scan": "scan_id",
    "day": "date_trunc('day', created_at)",
}


def record_usage(
    *,
    scan_id: int | None,
    agent: str,
    profile_id: int | None,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
    latency_ms: int,
    ok: bool = True,
    error: str = "",
) -> bool:
    """写一条调用记录；无库/失败返回 False，不阻塞 LLM 调用。"""
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO llm_usage
                    (scan_id, agent, profile_id, model, prompt_tokens, completion_tokens,
                     cost_usd, latency_ms, ok, error)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    scan_id,
                    agent,
                    profile_id,
                    model,
                    int(prompt_tokens or 0),
                    int(completion_tokens or 0),
                    float(cost_usd or 0.0),
                    int(latency_ms or 0),
                    bool(ok),
                    (error or "")[:500],
                ),
            )
            conn.commit()
        return True
    except Exception:  # noqa: BLE001 - 台账失败不阻塞主流程
        return False


def _parse_ts(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def summary(
    *,
    group_by: str = "agent",
    since: str | datetime | None = None,
    until: str | datetime | None = None,
) -> list[dict]:
    expr = _GROUP_EXPR.get(group_by)
    if expr is None:
        raise ValueError(f"unsupported group_by: {group_by}")
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        clauses: list[str] = []
        params: list[object] = []
        start = _parse_ts(since)
        end = _parse_ts(until)
        if start is not None:
            clauses.append("created_at >= %s")
            params.append(start)
        if end is not None:
            clauses.append("created_at < %s")
            params.append(end)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {expr} AS k, count(*) AS calls,
                       coalesce(sum(prompt_tokens),0) AS prompt_tokens,
                       coalesce(sum(completion_tokens),0) AS completion_tokens,
                       coalesce(sum(cost_usd),0) AS cost_usd,
                       coalesce(round(avg(latency_ms)),0) AS avg_latency_ms,
                       coalesce(sum(CASE WHEN ok THEN 1 ELSE 0 END),0) AS ok_calls
                FROM llm_usage{where}
                GROUP BY 1 ORDER BY 1
                """,
                params,
            )
            rows = cur.fetchall()
        return [
            {
                "key": str(r[0]) if r[0] is not None else "",
                "calls": int(r[1]),
                "prompt_tokens": int(r[2]),
                "completion_tokens": int(r[3]),
                "tokens": int(r[2]) + int(r[3]),
                "cost_usd": float(r[4]),
                "avg_latency_ms": int(r[5]),
                "ok_calls": int(r[6]),
            }
            for r in rows
        ]
    except ValueError:
        raise
    except Exception:  # noqa: BLE001
        return []


def _read_setting(key: str) -> str:
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT value FROM app_settings WHERE key=%s", (key,))
            row = cur.fetchone()
        return str(row[0]) if row else ""
    except Exception:  # noqa: BLE001
        return ""


def set_quota(*, tokens: int | None = None, usd: float | None = None) -> bool:
    try:
        from codesentry.db.pool import get_conn

        values: list[tuple[str, str]] = []
        if tokens is not None:
            values.append(("llm_quota_tokens", str(int(tokens))))
        if usd is not None:
            values.append(("llm_quota_usd", str(float(usd))))
        with get_conn() as conn, conn.cursor() as cur:
            for k, v in values:
                cur.execute(
                    "INSERT INTO app_settings (key, value) VALUES (%s,%s)"
                    " ON CONFLICT (key) DO UPDATE SET value=%s, updated_at=now()",
                    (k, v, v),
                )
            conn.commit()
        return True
    except Exception:  # noqa: BLE001
        return False


def quota_status() -> dict:
    used_tokens = 0
    used_usd = 0.0
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT coalesce(sum(prompt_tokens+completion_tokens),0), coalesce(sum(cost_usd),0)"
                " FROM llm_usage WHERE created_at >= date_trunc('month', now())"
            )
            row = cur.fetchone()
            used_tokens, used_usd = int(row[0]), float(row[1])
    except Exception:  # noqa: BLE001, S110
        pass
    tokens_limit = int(_read_setting("llm_quota_tokens") or 0)
    usd_limit = float(_read_setting("llm_quota_usd") or 0.0)

    def pct(used: float, limit: float) -> float:
        return round(used / limit * 100, 1) if limit > 0 else 0.0

    return {
        "period": "month",
        "now": datetime.now(UTC).isoformat(timespec="seconds"),
        "tokens_used": used_tokens,
        "usd_used": round(used_usd, 6),
        "tokens_limit": tokens_limit,
        "usd_limit": usd_limit,
        "tokens_pct": pct(used_tokens, tokens_limit),
        "usd_pct": pct(used_usd, usd_limit),
        "warn": max(pct(used_tokens, tokens_limit), pct(used_usd, usd_limit)) >= 80.0,
    }
