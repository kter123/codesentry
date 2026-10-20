"""M6.1 控制面 API：LLM Profiles / Agents / Usage / Audit / Prompts / Skills / Health。"""

from __future__ import annotations

import shutil
import time
from typing import Any

from fastapi import HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict

from codesentry.web.server import app


class ProfilePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    provider: str = "openai-compatible"
    protocol: str = "openai-compatible"
    model_prefix_policy: str = "strip"
    base_url: str
    api_key: str = ""
    fast_model: str = ""
    deep_model: str = ""
    temperature: float = 0.0
    max_tokens: int = 0
    timeout_s: int = 60
    max_concurrency: int = 4
    input_price_per_1k: float = 0.0
    output_price_per_1k: float = 0.0
    capabilities: dict = {}
    extra_headers: dict = {}
    model_catalog: list = []
    model_protocols: dict = {}
    quota_windows: list = []
    billing_mode: str = "metered"
    fallback_profile_id: int | None = None
    enabled: bool = True
    is_default: bool = False


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    provider: str | None = None
    protocol: str | None = None
    model_prefix_policy: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    fast_model: str | None = None
    deep_model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_s: int | None = None
    max_concurrency: int | None = None
    input_price_per_1k: float | None = None
    output_price_per_1k: float | None = None
    capabilities: dict | None = None
    extra_headers: dict | None = None
    model_catalog: list | None = None
    model_protocols: dict | None = None
    quota_windows: list | None = None
    billing_mode: str | None = None
    fallback_profile_id: int | None = None
    enabled: bool | None = None
    is_default: bool | None = None


def _public(profile) -> dict:
    from codesentry.control.profiles import bound_agents, to_public

    out = to_public(profile)
    out["bound_agents"] = bound_agents(profile.id) if profile.id else []
    return out


def _require_agent(name: str) -> None:
    from codesentry.agents.state import AGENT_NAMES

    if name not in AGENT_NAMES:
        raise HTTPException(404, f"unknown agent: {name}")


@app.get("/api/llm-profiles/presets")
async def llm_presets() -> dict:
    from codesentry.control.profiles import PRESETS

    return {"presets": PRESETS}


@app.get("/api/llm-profiles")
async def list_llm_profiles() -> dict:
    from codesentry.control.profiles import list_profiles

    return {"profiles": [_public(p) for p in list_profiles()]}


@app.post("/api/llm-profiles")
async def create_llm_profile(payload: ProfilePayload) -> dict:
    from codesentry.control.profiles import create_profile

    try:
        p = create_profile(payload.model_dump(exclude_unset=True), actor="api")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if p is None:
        raise HTTPException(503, "Profile 写入失败（DB 不可用或名称冲突）")
    return _public(p)


@app.put("/api/llm-profiles/{profile_id}")
async def update_llm_profile(profile_id: int, payload: ProfileUpdate) -> dict:
    from codesentry.control.profiles import update_profile

    try:
        p = update_profile(profile_id, payload.model_dump(exclude_unset=True), actor="api")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if p is None:
        raise HTTPException(404)
    return _public(p)


@app.delete("/api/llm-profiles/{profile_id}")
async def delete_llm_profile(profile_id: int) -> dict:
    from codesentry.control.profiles import delete_profile

    status = delete_profile(profile_id, actor="api")
    if status == "not_found":
        raise HTTPException(404)
    if status == "bound":
        raise HTTPException(409, "Profile 仍被 Agent 绑定，先解绑")
    if status != "ok":
        raise HTTPException(503, "删除失败")
    return {"ok": True}


@app.post("/api/llm-profiles/{profile_id}/default")
async def set_default_profile(profile_id: int) -> dict:
    from codesentry.control.profiles import set_default

    p = set_default(profile_id, actor="api")
    if p is None:
        raise HTTPException(404, "Profile 不存在或未启用")
    return _public(p)


def _test_profile_sync(profile_id: int) -> dict:
    from codesentry.agents.llm import LLMClient
    from codesentry.control.profiles import get_profile

    profile = get_profile(profile_id)
    if profile is None:
        raise HTTPException(404)
    started = time.monotonic()
    try:
        client = LLMClient.from_profile(profile, session_id=f"test-{profile_id}")
        text = client.complete("You are a connectivity test.", "Reply with OK.", model_role="fast")
        return {
            "ok": True,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "model": client.last_meta.get("model", profile.fast_model),
            "reply_len": len(text or ""),
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


@app.post("/api/llm-profiles/{profile_id}/test")
async def test_llm_profile(profile_id: int) -> dict:
    return await run_in_threadpool(_test_profile_sync, profile_id)


@app.post("/api/llm-profiles/{profile_id}/probe")
async def probe_llm_profile(profile_id: int, limit: int = 5) -> dict:
    from codesentry.control.profiles import probe_models

    return await run_in_threadpool(probe_models, profile_id, limit=limit)


class AgentPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool | None = None
    model_role: str | None = None
    llm_profile_id: int | None = None
    display_name: str | None = None
    capabilities: dict | None = None
    timeout_s: int | None = None
    max_iterations: int | None = None
    temperature_override: float | None = None
    budget_override: dict | None = None


@app.get("/api/agents/{name}")
async def get_agent(name: str) -> dict:
    _require_agent(name)
    from codesentry.agents.prompts import SEED_PROMPTS
    from codesentry.agents.skills import build_context_block
    from codesentry.config import get_settings
    from codesentry.control.agent_config import get_agent_config
    from codesentry.control.prompts import get_active
    from codesentry.control.skills import load_assigned_skills

    try:
        cfg = get_agent_config(name)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    active = get_active(name)
    s = get_settings()
    block, warnings = build_context_block(
        load_assigned_skills(name), s.skill_max_per, s.skill_max_total
    )
    return {
        "config": cfg,
        "prompt": active or {"version": None, "body": SEED_PROMPTS.get(name, ""), "fallback": True},
        "skills_block": block,
        "warnings": warnings,
    }


@app.put("/api/agents/{name}")
async def put_agent(name: str, payload: AgentPatch) -> dict:
    _require_agent(name)
    from codesentry.control.agent_config import update_agent_config

    try:
        cfg = update_agent_config(name, payload.model_dump(exclude_unset=True), actor="api")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if cfg is None:
        raise HTTPException(503, "Agent 配置写入失败（DB 不可用？）")
    return {"agent": cfg}


@app.get("/api/agents/{name}/stats")
async def agent_stats(name: str, days: int = 30) -> dict:
    _require_agent(name)
    from codesentry.control.agent_config import agent_stats as _stats

    return _stats(name, days)


@app.get("/api/agents/{name}/prompt")
async def agent_prompt(name: str) -> dict:
    _require_agent(name)
    from codesentry.agents.prompts import SEED_PROMPTS
    from codesentry.control.prompts import get_active

    active = get_active(name)
    if active:
        return {"agent": name, "version": active["version"], "body": active["body"], "fallback": False}
    return {"agent": name, "version": None, "body": SEED_PROMPTS.get(name, ""), "fallback": True}


@app.get("/api/agents/{name}/skills")
async def agent_skills(name: str) -> dict:
    _require_agent(name)
    from codesentry.control.skills import load_assigned_skills

    return {
        "agent": name,
        "skills": [
            {"name": s.name, "version": getattr(s, "version", None),
             "sha256": getattr(s, "body_sha256", ""), "priority": getattr(s, "priority", 100)}
            for s in load_assigned_skills(name)
        ],
    }


class DryRunPayload(BaseModel):
    state: dict | None = None


@app.post("/api/agents/{name}/dry-run")
async def agent_dry_run(name: str, payload: DryRunPayload | None = None) -> dict:
    _require_agent(name)
    from codesentry.agents.runtime import prepare_agent

    rt = prepare_agent(name, with_llm=False)
    system = rt.system()
    return {
        "agent": name,
        "enabled": rt.enabled,
        "prompt_version": rt.prompt_version,
        "prompt_fallback": rt.prompt_fallback,
        "system_prompt": system,
        "token_est": len(system) // 4,
        "skills": [
            {"name": getattr(s, "name", ""), "version": getattr(s, "version", None)}
            for s in rt.skills
        ],
        "capabilities": rt.capabilities,
        "warnings": rt.warnings,
        "input_keys": sorted((payload.state or {}).keys()) if payload else [],
    }


@app.post("/api/agents/{name}/preview-prompt")
async def agent_preview_prompt(name: str) -> dict:
    _require_agent(name)
    from codesentry.control.skills import preview_injection

    out = preview_injection([name])
    if name not in out:
        raise HTTPException(404)
    return {"agent": name, **out[name]}


@app.get("/api/usage/summary")
async def usage_summary(group_by: str = "agent", since: str | None = None,
                        until: str | None = None,
                        from_: str | None = Query(None, alias="from"),
                        to: str | None = None) -> dict:
    from codesentry.control.usage import summary

    since = since or from_
    until = until or to
    try:
        rows = summary(group_by=group_by, since=since, until=until)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"group_by": group_by, "rows": rows}


@app.get("/api/usage/quota")
async def usage_quota() -> dict:
    from codesentry.control.usage import quota_status

    return quota_status()


class CalibrationPayload(BaseModel):
    pairs: list[dict]


@app.get("/api/calibration")
async def get_calibration() -> dict:
    from codesentry.control.calibration import get_params

    return get_params()


@app.post("/api/calibration/fit")
async def fit_calibration(payload: CalibrationPayload) -> dict:
    from codesentry.control.calibration import fit_and_save

    if not payload.pairs:
        raise HTTPException(400, "pairs 不能为空")
    return fit_and_save(payload.pairs)


class QuotaPayload(BaseModel):
    tokens: int | None = None
    usd: float | None = None


@app.put("/api/usage/quota")
async def set_usage_quota(payload: QuotaPayload) -> dict:
    from codesentry.control.usage import quota_status, set_quota

    if not set_quota(tokens=payload.tokens, usd=payload.usd):
        raise HTTPException(503, "配额写入失败")
    return quota_status()


@app.get("/api/audit")
async def list_audit_log(limit: int = 100, target_type: str | None = None,
                         actor: str | None = None) -> dict:
    from codesentry.control.audit import list_audit

    return {"rows": list_audit(limit=limit, target_type=target_type, actor=actor)}


class ActivatePayload(BaseModel):
    version: int


@app.post("/api/prompts/{name}/activate")
async def activate_prompt(name: str, payload: ActivatePayload) -> dict:
    from codesentry.control.prompts import activate

    if not activate(name, payload.version, actor="api"):
        raise HTTPException(404)
    return {"ok": True, "name": name, "version": payload.version}


@app.get("/api/prompts/{name}/diff")
async def diff_prompt(name: str, a: int, b: int) -> dict:
    from codesentry.control.prompts import diff

    try:
        return {"name": name, "diff": diff(name, a, b)}
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


class LintPayload(BaseModel):
    body: str


@app.post("/api/prompts/lint")
async def lint_prompt(payload: LintPayload) -> dict:
    from codesentry.control.prompts import lint

    return lint(payload.body)


class PreviewPayload(BaseModel):
    agents: list[str]


class TemplatePayload(BaseModel):
    name: str
    config: dict
    activate: bool = False


class EvalPayload(BaseModel):
    agent: str
    version: int | None = None
    dataset: str = ""
    metrics: dict = {}


class WebhookPayload(BaseModel):
    url: str
    secret: str = ""
    events: list[str] = ["*"]


@app.get("/api/webhooks")
async def list_webhooks() -> dict:
    from codesentry.control.webhooks import list_webhooks as _list

    return {"webhooks": _list()}


@app.post("/api/webhooks")
async def create_webhook(payload: WebhookPayload) -> dict:
    from codesentry.control.webhooks import create_webhook as _create

    try:
        out = _create(payload.url, payload.secret, payload.events)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if out is None:
        raise HTTPException(503, "webhook 写入失败")
    return out


@app.delete("/api/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: int) -> dict:
    from codesentry.control.webhooks import delete_webhook as _delete

    if not _delete(webhook_id):
        raise HTTPException(404)
    return {"ok": True}


@app.get("/api/graph-templates")
async def list_graph_templates() -> dict:
    from codesentry.control.orchestration import list_templates

    return {"templates": list_templates()}


@app.post("/api/graph-templates")
async def create_graph_template(payload: TemplatePayload) -> dict:
    from codesentry.control.orchestration import create_template

    try:
        out = create_template(payload.name, payload.config, activate=payload.activate)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if out is None:
        raise HTTPException(503, "模板写入失败")
    return out


@app.post("/api/graph-templates/{template_id}/activate")
async def activate_graph_template(template_id: int) -> dict:
    from codesentry.control.orchestration import activate_template

    if not activate_template(template_id):
        raise HTTPException(404)
    return {"ok": True}


@app.post("/api/graph-templates/validate")
async def validate_graph_template(payload: TemplatePayload) -> dict:
    from codesentry.control.orchestration import validate

    return validate(payload.config)


@app.post("/api/prompts/eval")
async def record_prompt_eval(payload: EvalPayload) -> dict:
    from codesentry.control.prompts import record_eval

    if not record_eval(payload.agent, payload.version, payload.dataset, payload.metrics):
        raise HTTPException(503, "评测写入失败")
    return {"ok": True}


@app.get("/api/prompt-evals")
async def list_prompt_evals(agent: str | None = None) -> dict:
    from codesentry.control.prompts import list_evals

    return {"evals": list_evals(agent)}


@app.post("/api/skills/{name}/preview")
async def preview_skill(name: str, payload: PreviewPayload) -> dict:
    from codesentry.control.skills import preview_injection

    return {"skill": name, "agents": preview_injection(payload.agents, only={name})}


@app.get("/api/skills/{name}/usage")
async def skill_usage(name: str) -> dict:
    from codesentry.control.skills import usage

    return {"skill": name, "scans": usage(name)}


def _health_sync() -> dict:
    from codesentry.control.profiles import list_profiles

    db: dict[str, Any] = {"ok": False, "latency_ms": 0}
    queue = {"running_scans": 0}
    started = time.monotonic()
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.execute("SELECT count(*) FROM scans WHERE status='running'")
            queue["running_scans"] = int(cur.fetchone()[0])
        db = {"ok": True, "latency_ms": int((time.monotonic() - started) * 1000)}
    except Exception:  # noqa: BLE001, S110
        pass
    docker_info: dict[str, Any] = {"ok": False}
    try:
        import docker

        client = docker.from_env()
        docker_info = {"ok": True, "version": client.version().get("Version", "")}
        client.close()
    except Exception:  # noqa: BLE001, S110
        pass
    engines = {name: (shutil.which(name) or "") for name in ("semgrep", "codeql", "joern")}
    return {
        "db": db,
        "profiles": {"count": len(list_profiles())},
        "docker": docker_info,
        "engines": engines,
        "queue": queue,
    }


@app.get("/api/scans/{scan_id}/artifacts")
async def get_scan_artifacts(scan_id: int) -> dict:
    from codesentry.orchestrator.artifacts import list_artifacts

    return {"scan_id": scan_id, "artifacts": list_artifacts(scan_id)}


@app.get("/api/scans/{scan_id}/artifacts/verify")
async def verify_scan_artifacts(scan_id: int) -> dict:
    from codesentry.orchestrator.artifacts import verify_chain

    return verify_chain(scan_id)


@app.get("/api/health")
async def health() -> dict:
    return await run_in_threadpool(_health_sync)
