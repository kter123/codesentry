"""M5.3 管理面板 API：agents/prompts/skills/rules/reviews。"""

from __future__ import annotations

import hashlib
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
    from codesentry.control.agent_config import list_agent_configs

    return {"agents": list_agent_configs()}


class PromptPayload(BaseModel):
    name: str
    body: str


@app.get("/api/prompts")
async def list_prompts() -> dict:
    from codesentry.control.prompts import list_prompts as _list

    return {"prompts": _list()}


@app.get("/api/prompts/{name}/versions")
async def prompt_versions(name: str) -> dict:
    from codesentry.control.prompts import get_versions

    rows = get_versions(name)
    if not rows:
        raise HTTPException(404)
    return {"name": name, "versions": rows}


@app.post("/api/prompts")
async def create_prompt(payload: PromptPayload) -> dict:
    from codesentry.control.prompts import create_version

    nv = create_version(payload.name, payload.body, activate=True, actor="api")
    if nv is None:
        raise HTTPException(503, "prompt 写入失败（DB 不可用？）")
    return {"name": payload.name, "version": nv}


class RollbackPayload(BaseModel):
    version: int


@app.post("/api/prompts/{name}/rollback")
async def rollback_prompt(name: str, payload: RollbackPayload) -> dict:
    from codesentry.control.prompts import rollback

    nv = rollback(name, payload.version, actor="api")
    if nv is None:
        raise HTTPException(404)
    return {"name": name, "new_version": nv, "rolled_back_from": payload.version}


# ---- Skills ----
@app.post("/api/skills/upload")
async def skill_upload(payload: PromptPayload) -> dict:  # name+body(SKILL.md 正文)
    from codesentry.control.skills import upload_skill

    try:
        out = upload_skill(payload.body, actor="api")
    except ValueError as e:
        raise HTTPException(400, f"SKILL.md 校验失败：{e}") from e
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    return {"name": out["name"], "version": out["version"]}


@app.get("/api/skills")
async def list_skills() -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT s.name, s.description, s.enabled, min(v.version), max(v.version)"
                    " FROM skills s LEFT JOIN skill_versions v ON v.name=s.name GROUP BY s.name, s.description, s.enabled")
        rows = cur.fetchall()
        cur.execute("SELECT skill_name, agent, enabled, version_pin, priority FROM skill_assignments")
        assigns = cur.fetchall()
    out = []
    for n, d, en, vmin, vmax in rows:
        out.append({
            "name": n, "description": d, "enabled": en,
            "versions": vmax or 0,
            "assigned": {a: en2 for sn, a, en2, _vp, _pr in assigns if sn == n},
            "assignments": [
                {"agent": a, "enabled": en2, "version_pin": vp, "priority": pr}
                for sn, a, en2, vp, pr in assigns if sn == n
            ],
        })
    return {"skills": out}


class AssignPayload(BaseModel):
    agent: str
    enabled: bool = True
    version_pin: int | None = None
    priority: int = 100


@app.post("/api/skills/{name}/assign")
async def skill_assign(name: str, payload: AssignPayload) -> dict:
    from codesentry.control.skills import assign

    if not assign(name, payload.agent, enabled=payload.enabled,
                  version_pin=payload.version_pin, priority=payload.priority, actor="api"):
        raise HTTPException(503, "skill 分配失败（DB 不可用？）")
    return {"ok": True, "skill": name, "agent": payload.agent, "enabled": payload.enabled,
            "version_pin": payload.version_pin, "priority": payload.priority}


# ---- Rules ----
@app.get("/api/rules")
async def list_rules() -> dict:
    import yaml


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
        r = subprocess.run(["semgrep", "--validate", "--config", tmp], capture_output=True, text=True, timeout=120, check=False)  # noqa: ASYNC221
        ok = "found 0 configuration error" in (r.stdout + r.stderr)
        return {"ok": ok, "output": (r.stdout or r.stderr)[-800:]}
    finally:
        Path(tmp).unlink(missing_ok=True)


@app.post("/api/rules/save")
async def save_rules(payload: YamlPayload) -> dict:
    v = await validate_rules(payload)
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
        from codesentry.agents.poc_gen import run_poc_gen
        from codesentry.agents.report import run_report
        from codesentry.agents.retrieval import run_retrieval
        from codesentry.agents.triage import run_triage
        from codesentry.orchestrator.graph import build_graph
        from codesentry.orchestrator.human_review import human_review_node
        from codesentry.orchestrator.runner import run_scan_graph  # noqa: F401 保证 imports 环节一致

        # 用 stub scan 以避免重跑引擎——已 triaged 状态由 checkpointer 恢复
        snapshot = None
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT prompt_snapshot, skill_snapshot, llm_snapshot FROM scans WHERE id=%s",
                    (scan_id,),
                )
                row = cur.fetchone()
            if row and any(row):
                snapshot = {
                    "prompt_versions": row[0] or {},
                    "skills_snapshot": row[1] or {},
                    "llm_snapshot": row[2] or {},
                }
        except Exception:  # noqa: BLE001
            snapshot = None
        g = build_graph(
            scan_agent=lambda s: {},
            retrieval_agent=run_retrieval,
            triage_agent=run_triage,
            poc_agent=run_poc_gen,
            report_agent_fn=lambda s, out=f"work/scan-{scan_id}-resume-report": run_report(s, out),
            checkpointer=cp,
            scan_id_holder={"scan_id": scan_id, "budget": None, "snapshot": snapshot},
            human_review_node=human_review_node,
        )
        cfg = {"configurable": {"thread_id": f"scan-{scan_id}"}, "recursion_limit": 30}
        final = g.invoke(Command(resume=payload.decisions), config=cfg)
        try:
            with get_conn() as conn, conn.cursor() as cur:
                for d in payload.decisions:
                    if d.get("rule_id") is not None and d.get("line") is not None:
                        cur.execute(
                            "UPDATE findings SET verdict=%s WHERE scan_id=%s AND rule_id=%s AND line=%s",
                            (str(d.get("verdict") or "keep"), scan_id, d.get("rule_id"), d.get("line")),
                        )
                conn.commit()
        except Exception:  # noqa: BLE001, S110
            pass
        try:
            from codesentry.rag.experience import promote_findings

            promote_findings(scan_id, verdicts=("keep", "verified", "confirmed"))
        except Exception:  # noqa: BLE001, S110
            pass
        try:
            from codesentry.web.server import _notify

            _notify("review.completed", {"scan_id": scan_id,
                                         "kept": len(final.get("triaged_findings") or [])})
        except Exception:  # noqa: BLE001, S110
            pass
        return {"ok": True, "phase": final.get("phase"), "kept": len(final.get("triaged_findings") or [])}
    except Exception as e:
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
