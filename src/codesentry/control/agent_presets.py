"""自定义 Agent Preset（P1）：绑定到内置节点，覆盖 Prompt/工具/技能/能力。"""

from __future__ import annotations

import json
from typing import Any

from codesentry.agents.state import AGENT_NAMES


def _row(r: tuple) -> dict[str, Any]:
    keys = ["id", "name", "base_agent", "description", "system_prompt", "tools_allow",
            "skills_allow", "capabilities", "enabled", "version", "created_at", "updated_at"]
    out = dict(zip(keys, r))
    out["created_at"] = str(out["created_at"])
    out["updated_at"] = str(out["updated_at"])
    return out


def list_presets(base_agent: str = "") -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        sql = ("SELECT id, name, base_agent, description, system_prompt, tools_allow,"
               " skills_allow, capabilities, enabled, version, created_at, updated_at"
               " FROM agent_presets")
        params: list = []
        if base_agent:
            sql += " WHERE base_agent=%s"
            params.append(base_agent)
        sql += " ORDER BY id"
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [_row(r) for r in rows]
    except Exception:  # noqa: BLE001
        return []


def get_preset(preset_id: int) -> dict | None:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, base_agent, description, system_prompt, tools_allow,"
                " skills_allow, capabilities, enabled, version, created_at, updated_at"
                " FROM agent_presets WHERE id=%s",
                (int(preset_id),),
            )
            row = cur.fetchone()
        return _row(row) if row else None
    except Exception:  # noqa: BLE001
        return None


def create_preset(name: str, base_agent: str, *, description: str = "",
                  system_prompt: str = "", tools_allow: list[str] | None = None,
                  skills_allow: list[str] | None = None,
                  capabilities: dict | None = None, enabled: bool = True) -> dict:
    if base_agent not in AGENT_NAMES:
        raise ValueError(f"不支持的 base_agent：{base_agent}")
    if not str(name).strip():
        raise ValueError("preset 名称必填")
    if not str(system_prompt).strip():
        raise ValueError("system_prompt 必填")
    from codesentry.control.audit import audit_write
    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.db.pool import get_conn

    ensure_control_schema()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO agent_presets (name, base_agent, description, system_prompt,"
            " tools_allow, skills_allow, capabilities, enabled)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (name.strip(), base_agent, description, system_prompt,
             json.dumps(tools_allow or []), json.dumps(skills_allow or []),
             json.dumps(capabilities or {}), bool(enabled)),
        )
        pid = int(cur.fetchone()[0])
        conn.commit()
    audit_write("api", "create", "agent_preset", str(pid), None,
                {"name": name, "base_agent": base_agent})
    out = get_preset(pid)
    assert out is not None
    return out


def update_preset(preset_id: int, patch: dict) -> dict | None:
    current = get_preset(preset_id)
    if not current:
        return None
    if "base_agent" in patch and patch["base_agent"] not in AGENT_NAMES:
        raise ValueError(f"不支持的 base_agent：{patch['base_agent']}")
    fields = {
        "name": patch.get("name", current["name"]),
        "base_agent": patch.get("base_agent", current["base_agent"]),
        "description": patch.get("description", current["description"]),
        "system_prompt": patch.get("system_prompt", current["system_prompt"]),
        "tools_allow": patch.get("tools_allow", current["tools_allow"]),
        "skills_allow": patch.get("skills_allow", current["skills_allow"]),
        "capabilities": patch.get("capabilities", current["capabilities"]),
        "enabled": bool(patch.get("enabled", current["enabled"])),
    }
    from codesentry.control.audit import audit_write
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE agent_presets SET name=%s, base_agent=%s, description=%s,"
            " system_prompt=%s, tools_allow=%s, skills_allow=%s, capabilities=%s,"
            " enabled=%s, version=version+1, updated_at=now() WHERE id=%s",
            (fields["name"], fields["base_agent"], fields["description"],
             fields["system_prompt"], json.dumps(fields["tools_allow"]),
             json.dumps(fields["skills_allow"]), json.dumps(fields["capabilities"]),
             fields["enabled"], int(preset_id)),
        )
        conn.commit()
    audit_write("api", "update", "agent_preset", str(preset_id), current, fields)
    return get_preset(preset_id)


def delete_preset(preset_id: int) -> bool:
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE agent_configs SET preset_id=NULL WHERE preset_id=%s", (int(preset_id),))
        cur.execute("DELETE FROM agent_presets WHERE id=%s", (int(preset_id),))
        ok = cur.rowcount > 0
        conn.commit()
    return ok


def bind_preset(agent: str, preset_id: int | None) -> dict | None:
    if agent not in AGENT_NAMES:
        raise ValueError(f"unknown agent: {agent}")
    if preset_id is not None:
        preset = get_preset(preset_id)
        if preset is None:
            raise ValueError("preset 不存在")
        if preset["base_agent"] != agent:
            raise ValueError("preset 的 base_agent 与目标 Agent 不匹配")
    from codesentry.control.agent_config import update_agent_config

    return update_agent_config(agent, {"preset_id": preset_id})
