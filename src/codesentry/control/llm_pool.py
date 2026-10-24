"""LLM 池（M2）：有序故障转移链 + 进程级熔断 + 健康持久化。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

BACKOFF = [timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30)]
SOFT_TRIP_AFTER = 3

_STATE: dict[int, dict] = {}


def chain_profiles(primary_id: int | None = None) -> list:
    """激活/绑定配置链首，其余按 priority DESC；pool_exclude 不参与。"""
    from codesentry.control.profiles import get_profile, list_profiles

    profiles = [p for p in list_profiles() if p.enabled]
    primary = get_profile(int(primary_id)) if primary_id else None
    if primary is None:
        primary = next((p for p in profiles if p.is_default), profiles[0] if profiles else None)
    head = [primary] if primary is not None else []
    others = [
        p for p in profiles
        if p.id != getattr(primary, "id", None) and not p.pool_exclude
    ]
    others.sort(key=lambda p: (-int(p.priority or 0), int(p.id or 0)))
    return head + others


def _load(profile_id: int) -> dict:
    if profile_id in _STATE:
        return _STATE[profile_id]
    state = {"fails": 0, "trips": 0, "open_until": None, "last_error": "", "last_at": None}
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT fails, trips, open_until, last_error, last_at"
                " FROM llm_profile_health WHERE profile_id=%s",
                (int(profile_id),),
            )
            row = cur.fetchone()
        if row:
            state = {"fails": int(row[0] or 0), "trips": int(row[1] or 0),
                     "open_until": row[2], "last_error": row[3] or "", "last_at": row[4]}
    except Exception:  # noqa: BLE001, S110 - 无库时纯内存
        pass
    _STATE[profile_id] = state
    return state


def _persist(profile_id: int, state: dict) -> None:
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO llm_profile_health"
                " (profile_id, fails, trips, open_until, last_error, last_at)"
                " VALUES (%s,%s,%s,%s,%s,now())"
                " ON CONFLICT (profile_id) DO UPDATE SET fails=EXCLUDED.fails,"
                " trips=EXCLUDED.trips, open_until=EXCLUDED.open_until,"
                " last_error=EXCLUDED.last_error, last_at=now()",
                (int(profile_id), state["fails"], state["trips"],
                 state["open_until"], state["last_error"]),
            )
            conn.commit()
    except Exception:  # noqa: BLE001, S110
        pass


def is_open(profile_id: int) -> bool:
    state = _load(int(profile_id))
    until = state.get("open_until")
    if until is None:
        return False
    if isinstance(until, str):
        try:
            until = datetime.fromisoformat(until)
        except ValueError:
            return False
    return datetime.now(UTC) < until


def record_success(profile_id: int) -> None:
    state = _load(int(profile_id))
    state.update({"fails": 0, "open_until": None, "last_error": ""})
    _persist(int(profile_id), state)


def record_failure(profile_id: int, error: str, *, hard: bool | None = None) -> bool:
    state = _load(int(profile_id))
    state["fails"] = int(state.get("fails") or 0) + 1
    state["last_error"] = str(error)[:300]
    if hard is None:
        hard = _is_hard(error)
    if hard or state["fails"] >= SOFT_TRIP_AFTER:
        state["trips"] = int(state.get("trips") or 0) + 1
        rung = min(state["trips"] - 1, len(BACKOFF) - 1)
        state["open_until"] = datetime.now(UTC) + BACKOFF[rung]
        _persist(int(profile_id), state)
        return True
    _persist(int(profile_id), state)
    return False


def reset(profile_id: int) -> None:
    state = _load(int(profile_id))
    state.update({"fails": 0, "trips": 0, "open_until": None, "last_error": ""})
    _persist(int(profile_id), state)


def health_snapshot() -> list[dict]:
    from codesentry.control.profiles import list_profiles

    out = []
    for profile in list_profiles():
        state = _load(int(profile.id or 0))
        out.append({
            "profile_id": profile.id, "name": profile.name, "priority": profile.priority,
            "pool_exclude": profile.pool_exclude, "enabled": profile.enabled,
            "fails": state["fails"], "trips": state["trips"],
            "open": is_open(int(profile.id or 0)),
            "open_until": str(state["open_until"] or ""),
            "last_error": state["last_error"], "last_at": str(state["last_at"] or ""),
        })
    return out


def _is_hard(error: str) -> bool:
    text = str(error).lower()
    return any(x in text for x in (
        "401", "402", "403", "404", "unauthorized", "invalid api key",
        "insufficient", "quota", "no credit", "billing", "config",
    ))


def wait_seconds(profile_id: int) -> float:
    state = _load(int(profile_id))
    until = state.get("open_until")
    if until is None:
        return 0.0
    if isinstance(until, str):
        try:
            until = datetime.fromisoformat(until)
        except ValueError:
            return 0.0
    return max(0.0, (until - datetime.now(UTC)).total_seconds())


__all__ = [
    "BACKOFF", "chain_profiles", "health_snapshot", "is_open", "record_failure",
    "record_success", "reset", "wait_seconds",
]
