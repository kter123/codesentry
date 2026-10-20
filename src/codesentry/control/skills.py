"""Skills 分配、版本固定与注入预览（M6.1 FR-24 基础闭环）。"""

from __future__ import annotations

import hashlib

from codesentry.agents.skills import Skill, build_context_block, parse_skill_md


def _row_skill(row: tuple) -> Skill:
    name, description, version, body, sha, priority, pin = row
    skill = Skill(
        name=name,
        description=description or "",
        body=body,
        body_tokens_est=len(body) // 4,
        references=[],
    )
    skill.version = version  # type: ignore[attr-defined]
    skill.body_sha256 = sha  # type: ignore[attr-defined]
    skill.priority = priority  # type: ignore[attr-defined]
    skill.version_pin = pin  # type: ignore[attr-defined]
    return skill


def load_snapshot_skills(items: list[dict]) -> list[Skill]:
    """按扫描快照的 name/version 精确加载（不跟随最新版本）。"""
    out: list[Skill] = []
    if not items:
        return out
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            for item in items:
                name = str(item.get("name") or "")
                version = item.get("version")
                if not name:
                    continue
                if version is None:
                    cur.execute(
                        "SELECT version, body, body_sha256 FROM skill_versions"
                        " WHERE name=%s ORDER BY version DESC LIMIT 1",
                        (name,),
                    )
                else:
                    cur.execute(
                        "SELECT version, body, body_sha256 FROM skill_versions"
                        " WHERE name=%s AND version=%s",
                        (name, int(version)),
                    )
                row = cur.fetchone()
                if not row:
                    continue
                skill = Skill(
                    name=name,
                    description="",
                    body=row[1],
                    body_tokens_est=len(row[1]) // 4,
                    references=[],
                )
                skill.version = int(row[0])  # type: ignore[attr-defined]
                skill.body_sha256 = row[2] or ""  # type: ignore[attr-defined]
                out.append(skill)
    except Exception:  # noqa: BLE001
        return out
    return out


def load_assigned_skills(agent: str) -> list[Skill]:
    """按 priority 升序解析；version_pin 为空跟随最新版本。"""
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.name, s.description, sv.version, sv.body, sv.body_sha256,
                       sa.priority, sa.version_pin
                FROM skill_assignments sa
                JOIN skills s ON s.name = sa.skill_name AND s.enabled
                JOIN LATERAL (
                    SELECT version, body, body_sha256
                    FROM skill_versions v
                    WHERE v.name = sa.skill_name
                      AND (sa.version_pin IS NULL OR v.version = sa.version_pin)
                    ORDER BY version DESC LIMIT 1
                ) sv ON TRUE
                WHERE sa.agent = %s AND sa.enabled
                ORDER BY sa.priority ASC, s.name ASC
                """,
                (agent,),
            )
            rows = cur.fetchall()
        return [_row_skill(r) for r in rows]
    except Exception:  # noqa: BLE001
        return []


def skill_versions(agent: str) -> list[dict]:
    out: list[dict] = []
    for s in load_assigned_skills(agent):
        out.append({"name": s.name, "version": getattr(s, "version", None),
                    "body_sha256": getattr(s, "body_sha256", "")})
    return out


def assign(
    skill_name: str,
    agent: str,
    *,
    enabled: bool = True,
    version_pin: int | None = None,
    priority: int = 100,
    actor: str = "system",
) -> bool:
    try:
        from codesentry.control.audit import audit_write
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO skill_assignments (skill_name, agent, enabled, version_pin, priority)"
                " VALUES (%s,%s,%s,%s,%s)"
                " ON CONFLICT (skill_name, agent) DO UPDATE SET enabled=%s, version_pin=%s, priority=%s",
                (skill_name, agent, enabled, version_pin, int(priority),
                 enabled, version_pin, int(priority)),
            )
            conn.commit()
        audit_write(actor, "assign", "skill", f"{skill_name}:{agent}", None,
                    {"enabled": enabled, "version_pin": version_pin, "priority": priority})
        return True
    except Exception:  # noqa: BLE001
        return False


def upload_skill(text: str, actor: str = "system") -> dict:
    """解析 SKILL.md 并写入新版本；非法 frontmatter 抛 ValueError。"""
    skill = parse_skill_md(text)
    sha = hashlib.sha256(skill.body.encode("utf-8")).hexdigest()
    try:
        from codesentry.control.audit import audit_write
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO skills (name, description, enabled) VALUES (%s,%s,TRUE)"
                " ON CONFLICT (name) DO UPDATE SET description=EXCLUDED.description",
                (skill.name, skill.description),
            )
            cur.execute("SELECT coalesce(max(version),0) FROM skill_versions WHERE name=%s", (skill.name,))
            nv = int(cur.fetchone()[0]) + 1
            cur.execute(
                "INSERT INTO skill_versions (name, version, body, body_sha256) VALUES (%s,%s,%s,%s)",
                (skill.name, nv, skill.body, sha),
            )
            conn.commit()
        audit_write(actor, "upload", "skill", skill.name, None, {"version": nv, "sha256": sha})
        return {"name": skill.name, "version": nv, "sha256": sha}
    except Exception as e:
        raise RuntimeError(f"Skill 入库失败：{e}") from e


def preview_injection(agents: list[str], *, max_per: int = 8192, max_total: int = 32768,
                      only: set[str] | None = None) -> dict:
    from codesentry.agents.prompts import SEED_PROMPTS
    from codesentry.control.prompts import get_active

    out: dict[str, dict] = {}
    for agent in agents:
        active = get_active(agent)
        if active:
            prompt_text, version = active["body"], active["version"]
        else:
            prompt_text, version = SEED_PROMPTS.get(agent, ""), None
        assigned = load_assigned_skills(agent)
        if only:
            assigned = [s for s in assigned if s.name in only]
        block, warnings = build_context_block(assigned, max_per, max_total)
        out[agent] = {
            "prompt_version": version,
            "prompt_preview": prompt_text[:240],
            "skills_block": block,
            "skills_tokens_est": len(block) // 4,
            "prompt_tokens_est": len(prompt_text) // 4,
            "warnings": warnings,
        }
    return out


def usage(skill_name: str, limit: int = 50) -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        pattern = f'%"name": "{skill_name}"%'
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, created_at, status FROM scans WHERE skill_snapshot::text LIKE %s"
                " ORDER BY id DESC LIMIT %s",
                (pattern, max(1, min(int(limit), 200))),
            )
            rows = cur.fetchall()
        return [{"scan_id": r[0], "created_at": str(r[1]), "status": r[2]} for r in rows]
    except Exception:  # noqa: BLE001
        return []


def snapshot(agent: str) -> list[dict]:
    """扫描快照用：名称/版本/哈希（尊重 version_pin）。"""
    return [
        {
            "name": s.name,
            "version": getattr(s, "version", None),
            "sha256": getattr(s, "body_sha256", ""),
            "priority": getattr(s, "priority", 100),
        }
        for s in load_assigned_skills(agent)
    ]
