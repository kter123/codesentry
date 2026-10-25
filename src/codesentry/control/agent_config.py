"""Agent 配置与能力矩阵（M6.1 FR-21/FR-22）。"""

from __future__ import annotations

import json
from typing import Any

from codesentry.agents.state import AGENT_NAMES
from codesentry.control.audit import audit_write

AGENT_DEFAULTS: dict[str, dict[str, Any]] = {
    "recon": {
        "display_name": "Recon", "model_role": "fast", "enabled": True,
        "capabilities": {"engines": [], "network": False, "shell": False, "poc_exec": False},
        "timeout_s": 180, "max_iterations": 10,
        "budget_override": {"max_tokens": 60_000, "max_tool_calls": 80, "max_cost_usd": 1.0},
    },
    "scan": {
        "display_name": "Scan", "model_role": "fast", "enabled": True,
        "capabilities": {"engines": ["semgrep", "codeql", "joern"], "network": False,
                         "shell": True, "poc_exec": False},
        "timeout_s": 900, "max_iterations": 10,
        "budget_override": {"max_tokens": 60_000, "max_tool_calls": 80, "max_cost_usd": 1.0},
    },
    "retrieval": {
        "display_name": "Retrieval", "model_role": "fast", "enabled": True,
        "capabilities": {"engines": [], "network": False, "shell": False, "poc_exec": False},
        "timeout_s": 240, "max_iterations": 12,
        "budget_override": {"max_tokens": 120_000, "max_tool_calls": 150, "max_cost_usd": 2.5},
    },
    "audit": {
        "display_name": "Audit", "model_role": "deep", "enabled": True,
        "capabilities": {"engines": [], "network": False, "shell": False, "poc_exec": False},
        "timeout_s": 900, "max_iterations": 16,
        "budget_override": {"max_tokens": 400_000, "max_tool_calls": 400, "max_cost_usd": 10.0},
    },
    "deploy": {
        "display_name": "Deploy", "model_role": "deep", "enabled": True,
        "capabilities": {"engines": [], "network": True, "shell": False, "poc_exec": False},
        "timeout_s": 900, "max_iterations": 10,
        "budget_override": {"max_tokens": 150_000, "max_tool_calls": 120, "max_cost_usd": 2.0},
    },
    "triage": {
        "display_name": "Triage", "model_role": "deep", "enabled": True,
        "capabilities": {"engines": [], "network": False, "shell": False, "poc_exec": False},
        "timeout_s": 900, "max_iterations": 18,
        "budget_override": {"max_tokens": 500_000, "max_tool_calls": 600, "max_cost_usd": 12.0},
    },
    "poc_gen": {
        "display_name": "PoC Gen", "model_role": "deep", "enabled": True,
        "capabilities": {"engines": [], "network": True, "shell": True, "poc_exec": True},
        "timeout_s": 900, "max_iterations": 14,
        "budget_override": {"max_tokens": 300_000, "max_tool_calls": 350, "max_cost_usd": 8.0},
    },
    "report": {
        "display_name": "Report", "model_role": "fast", "enabled": True,
        "capabilities": {"engines": [], "network": False, "shell": False, "poc_exec": False},
        "timeout_s": 180, "max_iterations": 8,
        "budget_override": {"max_tokens": 80_000, "max_tool_calls": 80, "max_cost_usd": 1.5},
    },
}

_EDITABLE = {
    "enabled", "model_role", "llm_profile_id", "display_name",
    "capabilities", "timeout_s", "max_iterations", "temperature_override",
    "budget_override", "ab_json", "tools_allow", "skills_allow", "wrapup_prompt", "preset_id",
}


def _default(name: str) -> dict[str, Any]:
    d = AGENT_DEFAULTS[name]
    return {
        "name": name,
        "display_name": d["display_name"],
        "enabled": d["enabled"],
        "model_role": d["model_role"],
        "llm_profile_id": None,
        "preset_id": None,
        "capabilities": dict(d["capabilities"]),
        "timeout_s": d["timeout_s"],
        "max_iterations": d["max_iterations"],
        "temperature_override": None,
        "budget_override": dict(d.get("budget_override") or {}),
        "ab_json": {},
        "tools_allow": [],
        "skills_allow": [],
        "wrapup_prompt": "",
    }


def ensure_agent_configs() -> bool:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            for name in AGENT_NAMES:
                d = AGENT_DEFAULTS[name]
                cur.execute(
                    "INSERT INTO agent_configs (name, enabled, model_role, display_name, capabilities,"
                    " timeout_s, max_iterations) VALUES (%s,%s,%s,%s,%s,%s,%s)"
                    " ON CONFLICT (name) DO NOTHING",
                    (
                        name, d["enabled"], d["model_role"], d["display_name"],
                        json.dumps(d["capabilities"]), d["timeout_s"], d["max_iterations"],
                    ),
                )
            conn.commit()
        return True
    except Exception:  # noqa: BLE001
        return False


def get_agent_config(name: str) -> dict[str, Any]:
    if name not in AGENT_DEFAULTS:
        raise ValueError(f"unknown agent: {name}")
    out = _default(name)
    ensure_agent_configs()
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT enabled, model_role, llm_profile_id, display_name, capabilities,"
                " timeout_s, max_iterations, temperature_override, budget_override, ab_json,"
                " tools_allow, skills_allow, wrapup_prompt, preset_id"
                " FROM agent_configs WHERE name=%s",
                (name,),
            )
            row = cur.fetchone()
        if row:
            out.update({
                "enabled": bool(row[0]),
                "model_role": row[1] or out["model_role"],
                "llm_profile_id": row[2],
                "display_name": row[3] or out["display_name"],
                "capabilities": {**out["capabilities"], **(row[4] or {})},
                "timeout_s": int(row[5] or out["timeout_s"]),
                "max_iterations": int(row[6] or out["max_iterations"]),
                "temperature_override": row[7],
                "budget_override": row[8] or out.get("budget_override") or {},
                "ab_json": row[9] or {},
                "tools_allow": row[10] or [],
                "skills_allow": row[11] or [],
                "wrapup_prompt": row[12] or "",
                "preset_id": row[13],
            })
    except Exception:  # noqa: BLE001, S110
        pass
    return out


def list_agent_configs() -> list[dict[str, Any]]:
    return [get_agent_config(n) for n in AGENT_NAMES]


def update_agent_config(name: str, patch: dict, actor: str = "system") -> dict[str, Any] | None:
    if name not in AGENT_DEFAULTS:
        raise ValueError(f"unknown agent: {name}")
    before = get_agent_config(name)
    payload = {k: patch[k] for k in _EDITABLE if k in patch}
    if not payload:
        return before
    if "llm_profile_id" in payload and payload["llm_profile_id"] is not None:
        from codesentry.control.profiles import get_profile

        if get_profile(int(payload["llm_profile_id"])) is None:
            raise ValueError("llm_profile_id 不存在")
    if "capabilities" in payload:
        payload["capabilities"] = {**before.get("capabilities", {}), **payload["capabilities"]}
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        sets: list[str] = []
        vals: list[Any] = []
        for k, v in payload.items():
            sets.append(f"{k}=%s")
            vals.append(json.dumps(v) if k in (
                "capabilities", "budget_override", "ab_json", "tools_allow", "skills_allow"
            ) else v)
        sets.append("updated_at=now()")
        vals.append(name)
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(f"UPDATE agent_configs SET {', '.join(sets)} WHERE name=%s", vals)
            if cur.rowcount == 0:
                return None
            conn.commit()
        after = get_agent_config(name)
        audit_write(actor, "update", "agent_config", name, before, after)
        return after
    except Exception:  # noqa: BLE001
        return None


def effective_capabilities(name: str) -> dict[str, Any]:
    caps = dict(get_agent_config(name).get("capabilities") or {})
    if name == "poc_gen":
        from codesentry.config import get_settings

        if get_settings().poc_run == "off":
            caps.update({"network": False, "shell": False, "poc_exec": False})
    return caps


def capability_allows(name: str, capability: str) -> bool:
    caps = effective_capabilities(name)
    if capability in ("engines", "allowed_engines"):
        return bool(caps.get("engines"))
    return bool(caps.get(capability, False))


def agent_stats(name: str, days: int = 30) -> dict:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*),
                       coalesce(sum(CASE WHEN status='ok' THEN 1 ELSE 0 END),0),
                       coalesce(percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms),0),
                       coalesce(percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms),0),
                       coalesce(sum(tokens),0)
                FROM node_runs
                WHERE node=%s AND started_at >= now() - make_interval(days => %s)
                """,
                (name, max(1, int(days))),
            )
            row = cur.fetchone()
        calls = int(row[0] or 0)
        ok = int(row[1] or 0)
        return {
            "agent": name,
            "days": days,
            "calls": calls,
            "ok_calls": ok,
            "success_rate": round(ok / calls, 4) if calls else 0.0,
            "p50_ms": int(row[2] or 0),
            "p95_ms": int(row[3] or 0),
            "tokens": int(row[4] or 0),
        }
    except Exception:  # noqa: BLE001
        return {"agent": name, "days": days, "calls": 0, "ok_calls": 0,
                "success_rate": 0.0, "p50_ms": 0, "p95_ms": 0, "tokens": 0}
