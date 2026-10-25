"""配置导入导出（P1）：脱敏、可审计、merge/replace 均不删除安全主体。"""

from __future__ import annotations

from datetime import UTC, datetime

SCHEMA_VERSION = 1
SENSITIVE_SETTING_SUFFIXES = ("api_key", "password", "secret")
SENSITIVE_SETTING_KEYS = {"codeql_build_command"}


def _safe_setting(key: str) -> bool:
    return not key.endswith(SENSITIVE_SETTING_SUFFIXES) and key not in SENSITIVE_SETTING_KEYS


def export_config() -> dict:
    from codesentry.control.agent_config import list_agent_configs
    from codesentry.control.agent_presets import list_presets
    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.control.orchestration import list_templates
    from codesentry.control.webhooks import list_webhooks
    from codesentry.db.pool import get_conn

    ensure_control_schema()
    prompts: list[dict] = []
    skills: list[dict] = []
    settings: dict[str, str] = {}
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT agent, version, body, active, note, updated_by"
                " FROM prompt_versions ORDER BY agent, version"
            )
            prompts = [
                {"agent": r[0], "version": int(r[1]), "body": r[2],
                 "active": bool(r[3]), "note": r[4] or "", "updated_by": r[5] or ""}
                for r in cur.fetchall()
            ]
            cur.execute(
                "SELECT s.name, s.description, s.enabled, v.version, v.body"
                " FROM skills s LEFT JOIN skill_versions v ON v.name=s.name"
                " ORDER BY s.name, v.version"
            )
            for r in cur.fetchall():
                skills.append({"name": r[0], "description": r[1] or "",
                               "enabled": bool(r[2]), "version": r[3],
                               "body": r[4] or ""})
            cur.execute("SELECT key, value FROM app_settings ORDER BY key")
            settings = {str(k): str(v) for k, v in cur.fetchall() if _safe_setting(str(k))}
    except Exception:  # noqa: BLE001, S110
        pass
    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "prompts": prompts,
        "agents": list_agent_configs(),
        "agent_presets": list_presets(),
        "skills": skills,
        "graph_templates": list_templates(),
        "webhooks": list_webhooks(),
        "settings": settings,
    }


def _upsert_prompt(cur, item: dict) -> None:
    agent = str(item.get("agent") or "")
    version = int(item.get("version") or 0)
    if agent not in ("recon", "scan", "retrieval", "audit", "deploy", "triage",
                     "poc_gen", "report") or version <= 0:
        raise ValueError("非法 prompt 条目")
    body = str(item.get("body") or "")
    if item.get("active"):
        cur.execute("UPDATE prompt_versions SET active=FALSE WHERE agent=%s AND active", (agent,))
    cur.execute(
        "INSERT INTO prompt_versions (agent, version, body, active, note, updated_by)"
        " VALUES (%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (agent, version) DO UPDATE SET body=EXCLUDED.body,"
        " active=EXCLUDED.active, note=EXCLUDED.note, updated_by=EXCLUDED.updated_by",
        (agent, version, body, bool(item.get("active")), str(item.get("note") or ""),
         str(item.get("updated_by") or "import")),
    )


def import_config(doc: dict, mode: str = "merge") -> dict:
    if not isinstance(doc, dict) or int(doc.get("schema_version") or 0) != SCHEMA_VERSION:
        raise ValueError("不支持的配置 schema_version")
    if mode not in ("merge", "replace"):
        raise ValueError("mode 必须是 merge/replace")
    from codesentry.control.agent_config import update_agent_config
    from codesentry.control.agent_presets import create_preset, list_presets, update_preset
    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.control.webhooks import create_webhook, list_webhooks
    from codesentry.db.pool import get_conn

    ensure_control_schema()
    counts = {"prompts": 0, "agents": 0, "presets": 0, "skills": 0,
              "templates": 0, "webhooks": 0, "settings": 0}
    errors: list[str] = []
    with get_conn() as conn, conn.cursor() as cur:
        for item in doc.get("prompts") or []:
            try:
                _upsert_prompt(cur, item)
                counts["prompts"] += 1
            except Exception as e:  # noqa: BLE001
                errors.append(f"prompt: {str(e)[:120]}")
        for key, value in (doc.get("settings") or {}).items():
            if not _safe_setting(str(key)):
                continue
            cur.execute(
                "INSERT INTO app_settings (key, value) VALUES (%s,%s)"
                " ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()",
                (str(key), str(value)),
            )
            counts["settings"] += 1
        for item in doc.get("skills") or []:
            name = str(item.get("name") or "")
            if not name:
                continue
            cur.execute(
                "INSERT INTO skills (name, description, enabled) VALUES (%s,%s,%s)"
                " ON CONFLICT (name) DO UPDATE SET description=EXCLUDED.description,"
                " enabled=EXCLUDED.enabled",
                (name, str(item.get("description") or ""), bool(item.get("enabled", True))),
            )
            if item.get("version"):
                cur.execute(
                    "INSERT INTO skill_versions (name, version, body, body_sha256)"
                    " VALUES (%s,%s,%s,%s) ON CONFLICT (name, version) DO NOTHING",
                    (name, int(item["version"]), str(item.get("body") or ""),
                     __import__("hashlib").sha256(
                         str(item.get("body") or "").encode()).hexdigest()),
                )
            counts["skills"] += 1
        conn.commit()

    for item in doc.get("agents") or []:
        try:
            name = str(item.get("name") or "")
            patch = {k: item[k] for k in (
                "enabled", "model_role", "display_name", "capabilities", "timeout_s",
                "max_iterations", "temperature_override", "budget_override", "ab_json",
                "tools_allow", "skills_allow", "wrapup_prompt",
            ) if k in item}
            if update_agent_config(name, patch) is not None:
                counts["agents"] += 1
        except Exception as e:  # noqa: BLE001
            errors.append(f"agent: {str(e)[:120]}")
    existing_presets = {p["name"]: p for p in list_presets()}
    for item in doc.get("agent_presets") or []:
        try:
            name = str(item.get("name") or "")
            if name in existing_presets:
                update_preset(existing_presets[name]["id"], {
                    "base_agent": item.get("base_agent"),
                    "description": item.get("description", ""),
                    "system_prompt": item.get("system_prompt", ""),
                    "tools_allow": item.get("tools_allow") or [],
                    "skills_allow": item.get("skills_allow") or [],
                    "capabilities": item.get("capabilities") or {},
                    "enabled": bool(item.get("enabled", True)),
                })
            else:
                create_preset(name, str(item.get("base_agent") or ""),
                              description=str(item.get("description") or ""),
                              system_prompt=str(item.get("system_prompt") or ""),
                              tools_allow=item.get("tools_allow") or [],
                              skills_allow=item.get("skills_allow") or [],
                              capabilities=item.get("capabilities") or {},
                              enabled=bool(item.get("enabled", True)))
            counts["presets"] += 1
        except Exception as e:  # noqa: BLE001
            errors.append(f"preset: {str(e)[:120]}")
    existing_hooks = {h["url"] for h in list_webhooks()}
    for item in doc.get("webhooks") or []:
        try:
            url = str(item.get("url") or "")
            if url in existing_hooks:
                continue
            create_webhook(url, name=str(item.get("name") or ""),
                           kind=str(item.get("kind") or "generic"),
                           events=item.get("events") or ["*"],
                           headers=item.get("headers") or {})
            counts["webhooks"] += 1
        except Exception as e:  # noqa: BLE001
            errors.append(f"webhook: {str(e)[:120]}")
    return {"ok": not errors, "mode": mode, "counts": counts, "errors": errors}
