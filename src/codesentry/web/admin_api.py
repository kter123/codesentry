"""M5.3 管理面板 API：agents/prompts/skills/rules/reviews。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel

from codesentry.db.pool import get_conn
from codesentry.web.server import app


@app.get("/api/scans/{scan_id}/agents/timeline")
async def agent_timeline(scan_id: int) -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT node, started_at, ended_at, duration_ms, tokens, tool_calls, status, error"
            " FROM node_runs WHERE scan_id=%s ORDER BY started_at",
            (scan_id,),
        )
        rows = cur.fetchall()
    return {"scan_id": scan_id, "nodes": [
        {"node": n, "started": str(s), "ended": str(e), "duration_ms": d, "tokens": t,
         "tool_calls": c, "status": st, "error": err}
        for n, s, e, d, t, c, st, err in rows
    ]}


@app.get("/api/agents")
async def list_agents() -> dict:
    from codesentry.agents.state import AGENT_NAMES

    configs: dict[str, dict] = {}
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT name, enabled, model_role FROM agent_configs")
            for row in cur.fetchall():
                configs[row[0]] = {"enabled": row[1], "model_role": row[2]}
    except Exception:  # noqa: BLE001, S110
        pass
    return {"agents": [
        {"name": n, "enabled": configs.get(n, {}).get("enabled", True),
         "model_role": configs.get(n, {}).get("model_role", "deep")}
        for n in AGENT_NAMES
    ]}


class PromptPayload(BaseModel):
    name: str
    body: str


@app.get("/api/prompts")
async def list_prompts() -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ON (agent) agent, version, body FROM prompt_versions ORDER BY agent, version DESC"
        )
        rows = cur.fetchall()
    return {"prompts": [{"name": n, "latest_version": v, "preview": (b or "")[:120]} for n, v, b in rows]}


@app.get("/api/prompts/{name}/versions")
async def prompt_versions(name: str) -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT version, body, created_at FROM prompt_versions WHERE agent=%s ORDER BY version DESC", (name,))
        rows = cur.fetchall()
    if not rows:
        raise HTTPException(404)
    return {"name": name, "versions": [{"version": v, "body": b, "created": str(c)} for v, b, c in rows]}


@app.post("/api/prompts")
async def create_prompt(payload: PromptPayload) -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT coalesce(max(version),0) FROM prompt_versions WHERE agent=%s", (payload.name,))
        nv = cur.fetchone()[0] + 1
        cur.execute(
            "INSERT INTO prompt_versions (agent, version, body, active) VALUES (%s,%s,%s,TRUE)",
            (payload.name, nv, payload.body),
        )
        conn.commit()
    return {"name": payload.name, "version": nv}


class RollbackPayload(BaseModel):
    version: int


@app.post("/api/prompts/{name}/rollback")
async def rollback_prompt(name: str, payload: RollbackPayload) -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT body FROM prompt_versions WHERE agent=%s AND version=%s", (name, payload.version))
        r = cur.fetchone()
        if not r:
            raise HTTPException(404)
        body = r[0]
        cur.execute("SELECT coalesce(max(version),0) FROM prompt_versions WHERE agent=%s", (name,))
        nv = cur.fetchone()[0] + 1
        cur.execute(
            "INSERT INTO prompt_versions (agent, version, body, active) VALUES (%s,%s,%s,TRUE)",
            (name, nv, body),
        )
        conn.commit()
    return {"name": name, "new_version": nv, "rolled_back_from": payload.version}


# ---- Skills ----
@app.post("/api/skills/upload")
async def skill_upload(payload: PromptPayload) -> dict:  # name+body(SKILL.md 正文)
    from codesentry.agents.skills import parse_skill_md

    try:
        skill = parse_skill_md(payload.body)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"SKILL.md 校验失败：{e}") from e
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO skills (name, description, enabled) VALUES (%s,%s,TRUE) ON CONFLICT (name) DO NOTHING",
                    (skill.name, skill.description))
        cur.execute("SELECT coalesce(max(version),0) FROM skill_versions WHERE name=%s", (skill.name,))
        nv = cur.fetchone()[0] + 1
        cur.execute("INSERT INTO skill_versions (name, version, body, body_sha256) VALUES (%s,%s,%s,%s)",
                    (skill.name, nv, skill.body, hashlib.sha256(skill.body.encode()).hexdigest()))
        conn.commit()
    return {"name": skill.name, "version": nv}


@app.get("/api/skills")
async def list_skills() -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT s.name, s.description, s.enabled, min(v.version), max(v.version)"
                    " FROM skills s LEFT JOIN skill_versions v ON v.name=s.name GROUP BY s.name, s.description, s.enabled")
        rows = cur.fetchall()
        cur.execute("SELECT skill_name, agent, enabled FROM skill_assignments")
        assigns = cur.fetchall()
    out = []
    for n, d, en, vmin, vmax in rows:
        out.append({
            "name": n, "description": d, "enabled": en,
            "versions": vmax or 0,
            "assigned": {a: en2 for sn, a, en2 in assigns if sn == n},
        })
    return {"skills": out}


class AssignPayload(BaseModel):
    agent: str
    enabled: bool = True


@app.post("/api/skills/{name}/assign")
async def skill_assign(name: str, payload: AssignPayload) -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO skill_assignments (skill_name, agent, enabled) VALUES (%s,%s,%s)"
            " ON CONFLICT (skill_name, agent) DO UPDATE SET enabled=%s",
            (name, payload.agent, payload.enabled, payload.enabled),
        )
        conn.commit()
    return {"ok": True, "skill": name, "agent": payload.agent, "enabled": payload.enabled}


# ---- Rules ----
@app.get("/api/rules")
async def list_rules() -> dict:
    import yaml

    from codesentry.config import get_settings

    rule_path = Path("rules/codesentry-core.yml")
    if not rule_path.exists():
        return {"rules": []}
    doc = yaml.safe_load(rule_path.read_text())
    out = []
    for r in doc.get("rules", []):
        out.append({
            "id": r["id"], "languages": r.get("languages", []),
            "severity": r.get("severity"), "cwe": (r.get("metadata") or {}).get("cwe", ""),
            "message": r.get("message", ""),
        })
    return {"rules": out}


@app.get("/api/rules/{rule_id}")
async def get_rule(rule_id: str) -> dict:
    import yaml

    doc = yaml.safe_load(Path("rules/codesentry-core.yml").read_text())
    for r in doc.get("rules", []):
        if r["id"] == rule_id or r["id"].endswith("." + rule_id):
            return {"rule": r}
    raise HTTPException(404)


class YamlPayload(BaseModel):
    yaml: str


@app.post("/api/rules/validate")
async def validate_rules(payload: YamlPayload) -> dict:
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
        f.write(payload.yaml)
        tmp = f.name
    try:
        r = subprocess.run(["semgrep", "--validate", "--config", tmp], capture_output=True, text=True, timeout=120)
        ok = "found 0 configuration error" in (r.stdout + r.stderr)
        return {"ok": ok, "output": (r.stdout or r.stderr)[-800:]}
    finally:
        Path(tmp).unlink(missing_ok=True)


@app.post("/api/rules/save")
async def save_rules(payload: YamlPayload) -> dict:
    v = validate_rules(payload)
    if not v["ok"]:
        raise HTTPException(400, v["output"][:300])
    body = payload.yaml
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT coalesce(max(version),0) FROM rule_sets WHERE name='codesentry-core'")
        nv = cur.fetchone()[0] + 1
        cur.execute(
            "INSERT INTO rule_sets (name, version, body, body_sha256) VALUES ('codesentry-core',%s,%s,%s)",
            (nv, body, hashlib.sha256(body.encode()).hexdigest()),
        )
        conn.commit()
    Path("rules/codesentry-core.yml").write_text(body, encoding="utf-8")
    return {"ok": True, "version": nv}


# ---- Reviews（复核队列） ----
class ResumePayload(BaseModel):
    decisions: list[dict]


@app.post("/api/scans/{scan_id}/resume")
async def resume_scan(scan_id: int, payload: ResumePayload) -> dict:
    from langgraph.types import Command

    from codesentry.orchestrator.checkpointer import checkpointer as _cp

    cp_ctx = _cp()
    cp = cp_ctx.__enter__()
    try:
        from codesentry.orchestrator.graph import build_graph
        from codesentry.agents.report import run_report
        from codesentry.agents.retrieval import run_retrieval
        from codesentry.agents.scan import run_scan_agent
        from codesentry.agents.triage import run_triage
        from codesentry.agents.poc_gen import run_poc_gen
        from codesentry.orchestrator.human_review import human_review_node
        from codesentry.orchestrator.runner import run_scan_graph  # noqa: F401 保证 imports 环节一致

        # 用 stub scan 以避免重跑引擎——已 triaged 状态由 checkpointer 恢复
        g = build_graph(
            scan_agent=lambda s: {},
            retrieval_agent=run_retrieval,
            triage_agent=run_triage,
            poc_agent=run_poc_gen,
            report_agent_fn=lambda s, out=f"work/scan-{scan_id}-resume-report": run_report(s, out),
            checkpointer=cp,
            scan_id_holder={"scan_id": scan_id, "budget": None},
            human_review_node=human_review_node,
        )
        cfg = {"configurable": {"thread_id": f"scan-{scan_id}"}, "recursion_limit": 30}
        final = g.invoke(Command(resume=payload.decisions), config=cfg)
        return {"ok": True, "phase": final.get("phase"), "kept": len(final.get("triaged_findings") or [])}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"resume 失败：{e}") from e
    finally:
        cp_ctx.__exit__(None, None, None)


@app.get("/api/reviews")
async def review_queue() -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT s.id, s.repo_path, s.status, s.created_at FROM scans s"
            " JOIN node_runs n ON n.scan_id = s.id AND n.status='interrupted'"
        )
        rows = cur.fetchall()
    return {"queue": [{"id": r[0], "repo_path": r[1], "status": r[2], "created": str(r[3])} for r in rows]}
