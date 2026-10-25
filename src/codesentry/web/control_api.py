"""M6.1 控制面 API：LLM Profiles / Agents / Usage / Audit / Prompts / Skills / Health。"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
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


@app.get("/api/llm-profiles/health")
async def llm_health() -> dict:
    from codesentry.control.llm_pool import health_snapshot

    return {"profiles": health_snapshot()}


@app.post("/api/llm-profiles/{profile_id}/recover")
async def llm_recover(profile_id: int) -> dict:
    from codesentry.control.llm_pool import reset

    reset(profile_id)
    return {"ok": True, "profile_id": profile_id}


@app.get("/api/llm-calls")
async def llm_calls(profile_id: int | None = None, limit: int = 50) -> dict:
    from codesentry.db.pool import get_conn

    sql = ("SELECT id, scan_id, agent, profile_id, model, request_preview, response_preview,"
           " prompt_tokens, completion_tokens, cost_usd, latency_ms, ok, error, created_at"
           " FROM llm_calls")
    params: list = []
    if profile_id is not None:
        sql += " WHERE profile_id=%s"
        params.append(int(profile_id))
    sql += " ORDER BY id DESC LIMIT %s"
    params.append(max(1, min(int(limit), 200)))
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    keys = ["id", "scan_id", "agent", "profile_id", "model", "request_preview",
            "response_preview", "prompt_tokens", "completion_tokens", "cost_usd",
            "latency_ms", "ok", "error", "created_at"]
    return {"calls": [dict(zip(keys, (*(r[:-1]), str(r[-1])))) for r in rows]}


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
    ab_json: dict | None = None
    tools_allow: list | None = None
    skills_allow: list | None = None
    wrapup_prompt: str | None = None


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


class ComparePayload(BaseModel):
    state: dict = {}
    prompt_a: int | None = None
    prompt_b: int | None = None
    preset_a: int | None = None
    preset_b: int | None = None
    use_llm: bool = False


def _compare_prompt(agent: str, *, version: int | None, preset_id: int | None,
                    variables: dict) -> dict:
    from codesentry.agents.prompts import SEED_PROMPTS, compose_prompt
    from codesentry.control.agent_presets import get_preset
    from codesentry.control.prompts import get_active, get_version

    if preset_id:
        preset = get_preset(int(preset_id))
        if not preset:
            raise ValueError("preset 不存在")
        if preset["base_agent"] != agent:
            raise ValueError("preset base_agent 不匹配")
        body = compose_prompt(agent, preset["system_prompt"], variables, force_tail=True)
        return {"label": f"preset:{preset_id}", "body": body,
                "version": None, "preset_id": preset_id}
    if version is not None:
        pv = get_version(agent, int(version))
        if not pv:
            raise ValueError(f"prompt 版本不存在：{version}")
        return {"label": f"v{version}",
                "body": compose_prompt(agent, pv["body"], variables),
                "version": int(version), "preset_id": None}
    active = get_active(agent)
    if active:
        return {"label": f"v{active['version']}",
                "body": compose_prompt(agent, active["body"], variables),
                "version": int(active["version"]), "preset_id": None}
    return {"label": "seed", "body": compose_prompt(agent, SEED_PROMPTS.get(agent, ""), variables),
            "version": None, "preset_id": None}


@app.post("/api/agents/{name}/compare")
async def compare_agent_prompts(name: str, payload: ComparePayload) -> dict:
    _require_agent(name)
    import difflib

    variables = {"agent": name, "scan_id": "0"}
    try:
        a = _compare_prompt(name, version=payload.prompt_a, preset_id=payload.preset_a,
                            variables=variables)
        b = _compare_prompt(name, version=payload.prompt_b, preset_id=payload.preset_b,
                            variables=variables)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    result: dict[str, Any] = {
        "agent": name,
        "a": {**a, "token_est": len(a["body"]) // 4},
        "b": {**b, "token_est": len(b["body"]) // 4},
        "diff": "\n".join(difflib.unified_diff(
            a["body"].splitlines(), b["body"].splitlines(),
            fromfile=a["label"], tofile=b["label"], lineterm="",
        )),
        "used_llm": False,
    }
    if payload.use_llm:
        from codesentry.agents.llm import LLMClient

        client = LLMClient.for_agent(name, scan_id=0)
        user = __import__("json").dumps(payload.state or {}, ensure_ascii=False)[:12000]
        for key in ("a", "b"):
            try:
                result[key]["output"] = client.complete(
                    result[key]["body"], user, model_role="deep"
                )[:4000]
            except Exception as e:  # noqa: BLE001
                result[key]["error"] = str(e)[:200]
        result["used_llm"] = True
    return result


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


class PromptPreviewPayload(BaseModel):
    body: str | None = None
    variables: dict = {}


@app.get("/api/prompts/{name}/vars")
async def prompt_vars(name: str) -> dict:
    from codesentry.agents.prompts import prompt_vars as _vars

    return {"agent": name, "variables": _vars(name)}


@app.post("/api/prompts/{name}/preview")
async def preview_prompt(name: str, payload: PromptPreviewPayload) -> dict:
    from codesentry.control.prompts import preview

    return preview(name, payload.body, payload.variables)


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


class EvalRunPayload(BaseModel):
    agent: str
    version: int | None = None
    dataset: str = "selfbuilt"
    limit: int = 10


@app.post("/api/prompts/eval/run")
async def run_prompt_eval(payload: EvalRunPayload) -> dict:
    from codesentry.control.prompts import run_prompt_eval as _run

    try:
        return await run_in_threadpool(
            _run, payload.agent, payload.version, payload.dataset, payload.limit
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(503, f"评测失败：{str(e)[:200]}") from e


class AgentPresetPayload(BaseModel):
    name: str
    base_agent: str
    description: str = ""
    system_prompt: str
    tools_allow: list[str] = []
    skills_allow: list[str] = []
    capabilities: dict = {}
    enabled: bool = True


class AgentPresetPatch(BaseModel):
    name: str | None = None
    base_agent: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    tools_allow: list[str] | None = None
    skills_allow: list[str] | None = None
    capabilities: dict | None = None
    enabled: bool | None = None


class BindPresetPayload(BaseModel):
    preset_id: int | None = None


@app.get("/api/agent-presets")
async def list_agent_presets(base_agent: str = "") -> dict:
    from codesentry.control.agent_presets import list_presets

    return {"presets": list_presets(base_agent)}


@app.post("/api/agent-presets")
async def create_agent_preset(payload: AgentPresetPayload) -> dict:
    from codesentry.control.agent_presets import create_preset

    try:
        return create_preset(payload.name, payload.base_agent,
                             description=payload.description,
                             system_prompt=payload.system_prompt,
                             tools_allow=payload.tools_allow,
                             skills_allow=payload.skills_allow,
                             capabilities=payload.capabilities,
                             enabled=payload.enabled)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.put("/api/agent-presets/{preset_id}")
async def update_agent_preset(preset_id: int, payload: AgentPresetPatch) -> dict:
    from codesentry.control.agent_presets import update_preset

    try:
        out = update_preset(preset_id, payload.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if out is None:
        raise HTTPException(404)
    return out


@app.delete("/api/agent-presets/{preset_id}")
async def delete_agent_preset(preset_id: int) -> dict:
    from codesentry.control.agent_presets import delete_preset

    if not delete_preset(preset_id):
        raise HTTPException(404)
    return {"ok": True}


@app.post("/api/agents/{name}/bind-preset")
async def bind_agent_preset(name: str, payload: BindPresetPayload) -> dict:
    _require_agent(name)
    from codesentry.control.agent_presets import bind_preset

    try:
        out = bind_preset(name, payload.preset_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if out is None:
        raise HTTPException(503, "绑定失败")
    return {"agent": out}


class ConfigImportPayload(BaseModel):
    doc: dict
    mode: str = "merge"


@app.get("/api/config/export")
async def export_config() -> dict:
    from codesentry.control.config_io import export_config as _export

    return _export()


@app.post("/api/config/import")
async def import_config(payload: ConfigImportPayload) -> dict:
    from codesentry.control.config_io import import_config as _import

    try:
        return _import(payload.doc, payload.mode)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class PocTargetPayload(BaseModel):
    name: str
    base_url: str
    allowed_hosts: list[str]
    expires_at: str = ""
    enabled: bool = True


@app.get("/api/poc-targets")
async def list_poc_targets() -> dict:
    from codesentry.control.poc_targets import list_targets

    return {"targets": list_targets()}


@app.post("/api/poc-targets")
async def create_poc_target(payload: PocTargetPayload) -> dict:
    from datetime import datetime

    from codesentry.control.poc_targets import create_target

    expires = None
    if payload.expires_at:
        try:
            expires = datetime.fromisoformat(payload.expires_at)
        except ValueError as e:
            raise HTTPException(400, "expires_at 必须是 ISO8601") from e
    try:
        return create_target(payload.name, payload.base_url, payload.allowed_hosts,
                             expires, payload.enabled)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.delete("/api/poc-targets/{target_id}")
async def delete_poc_target(target_id: int) -> dict:
    from codesentry.control.poc_targets import delete_target

    if not delete_target(target_id):
        raise HTTPException(404)
    return {"ok": True}


@app.post("/api/poc-targets/{target_id}/probe")
async def probe_poc_target(target_id: int) -> dict:
    from codesentry.control.poc_targets import probe_target

    try:
        return await run_in_threadpool(probe_target, target_id)
    except ValueError as e:
        raise HTTPException(403, str(e)) from e


class KnowledgePackPayload(BaseModel):
    name: str
    content: str
    kind: str = "vuln"
    lang: str = ""
    framework: str = ""
    cwe: int = 0


class KnowledgePackPatch(BaseModel):
    name: str | None = None
    content: str | None = None
    kind: str | None = None
    lang: str | None = None
    framework: str | None = None
    cwe: int | None = None
    enabled: bool | None = None


@app.get("/api/knowledge-packs")
async def knowledge_packs(kind: str = "") -> dict:
    from codesentry.control.knowledge_packs import list_packs, seed_builtins

    seed_builtins()
    return {"packs": list_packs(kind)}


@app.post("/api/knowledge-packs")
async def create_knowledge_pack(payload: KnowledgePackPayload) -> dict:
    from codesentry.control.knowledge_packs import create_pack

    try:
        return create_pack(payload.name, payload.content, kind=payload.kind,
                           lang=payload.lang, framework=payload.framework,
                           cwe=payload.cwe)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.put("/api/knowledge-packs/{pack_id}")
async def update_knowledge_pack(pack_id: int, payload: KnowledgePackPatch) -> dict:
    from codesentry.control.knowledge_packs import update_pack

    out = update_pack(pack_id, payload.model_dump(exclude_unset=True))
    if out is None:
        raise HTTPException(404)
    return out


@app.delete("/api/knowledge-packs/{pack_id}")
async def delete_knowledge_pack(pack_id: int) -> dict:
    from codesentry.control.knowledge_packs import delete_pack

    if not delete_pack(pack_id):
        raise HTTPException(404)
    return {"ok": True}


class InstantAnalysisPayload(BaseModel):
    code: str
    filename: str = "snippet.py"
    oss: bool = False


@app.post("/api/instant-analysis")
async def instant_analysis(payload: InstantAnalysisPayload) -> dict:
    import uuid
    from pathlib import Path

    from codesentry.web.server import _insert_scan, _run_scan_bg, _work_root

    if len(payload.code.encode("utf-8")) > 200_000:
        raise HTTPException(413, "code too large")
    name = Path(payload.filename or "snippet.py").name
    job = uuid.uuid4().hex[:10]
    repo = _work_root() / f"instant-{job}" / "src"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(payload.code, encoding="utf-8")
    scan_id = _insert_scan(str(repo), bool(payload.oss))
    out_dir = str(_work_root() / f"instant-{job}" / "codesentry-report")
    _run_scan_bg(scan_id, str(repo), bool(payload.oss), out_dir)
    return {"ok": True, "scan_id": scan_id, "repo": str(repo)}


@app.get("/api/dashboard")
async def dashboard() -> dict:
    from codesentry.db.pool import get_conn

    out: dict = {}
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM scans")
            out["scans"] = int(cur.fetchone()[0])
            cur.execute("SELECT count(*) FROM findings")
            out["findings"] = int(cur.fetchone()[0])
            cur.execute("SELECT verdict,count(*) FROM findings GROUP BY verdict")
            out["by_verdict"] = {str(k or "candidate"): int(v) for k, v in cur.fetchall()}
            cur.execute("SELECT status,count(*) FROM audit_paths GROUP BY status")
            out["paths"] = {str(k): int(v) for k, v in cur.fetchall()}
            cur.execute("SELECT count(*) FROM verification_runs WHERE verdict='verified'")
            out["verified_runs"] = int(cur.fetchone()[0])
            cur.execute("SELECT coalesce(sum(tokens),0) FROM node_runs")
            out["tokens"] = int(cur.fetchone()[0] or 0)
            cur.execute("SELECT tool,status,count(*) FROM tool_runs GROUP BY tool,status")
            out["tools"] = [{"tool": r[0], "status": r[1], "count": int(r[2])}
                            for r in cur.fetchall()]
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:200]
    return out


@app.get("/api/scans/{scan_id}/report/html")
async def report_html(scan_id: int):
    from pathlib import Path

    from fastapi.responses import HTMLResponse

    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT report_dir FROM scans WHERE id=%s", (int(scan_id),))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404)
    path = Path(str(row[0] or "")) / "report.md"
    if not path.is_file():
        raise HTTPException(404, "report not ready")
    import html

    body = html.escape(path.read_text(encoding="utf-8", errors="replace"))
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>CodeSentry scan {scan_id}</title></head><body><pre>{body}</pre>"
        "</body></html>"
    )


@app.get("/api/scans/{scan_id}/evidence/export")
async def export_evidence(scan_id: int):
    import io
    import json
    import zipfile
    from pathlib import Path

    from fastapi.responses import StreamingResponse

    from codesentry.control.harness import list_runs
    from codesentry.db.pool import get_conn
    from codesentry.orchestrator.events import list_events

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT report_dir FROM scans WHERE id=%s", (int(scan_id),))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404)
        cur.execute(
            "SELECT id, rule_id, cwe, severity, confidence, file, line, message, engine,"
            " verdict, path_id FROM findings WHERE scan_id=%s ORDER BY id",
            (int(scan_id),),
        )
        findings = [dict(zip(
            ["id", "rule_id", "cwe", "severity", "confidence", "file", "line",
             "message", "engine", "verdict", "path_id"], r)) for r in cur.fetchall()]
    report_dir = Path(str(row[0] or ""))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("findings.json", json.dumps(findings, ensure_ascii=False, indent=2))
        z.writestr("verifications.json", json.dumps(list_runs(scan_id), ensure_ascii=False, indent=2))
        z.writestr("events.json", json.dumps(list_events(scan_id, 0, 1000), ensure_ascii=False, indent=2))
        for name in ("report.md", "report.sarif"):
            p = report_dir / name
            if p.is_file():
                z.writestr(name, p.read_text(encoding="utf-8", errors="replace"))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f"attachment; filename=scan-{scan_id}-evidence.zip"})


class WebhookPayload(BaseModel):
    name: str = ""
    kind: str = "generic"
    url: str = ""
    secret: str = ""
    events: list[str] = ["*"]
    headers: dict[str, str] = {}


@app.get("/api/webhooks")
async def list_webhooks() -> dict:
    from codesentry.control.webhooks import list_webhooks as _list

    return {"webhooks": _list()}


@app.post("/api/webhooks")
async def create_webhook(payload: WebhookPayload) -> dict:
    from codesentry.control.webhooks import create_webhook as _create

    try:
        out = _create(payload.url, payload.secret, payload.events,
                      name=payload.name, kind=payload.kind, headers=payload.headers)
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


@app.post("/api/webhooks/{webhook_id}/test")
async def test_webhook_endpoint(webhook_id: int) -> dict:
    from codesentry.control.webhooks import test_webhook

    try:
        return test_webhook(webhook_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


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
    engine_details: dict[str, dict] = {}
    try:
        from codesentry.control.engine_config import codeql_status, resolve_codeql_config

        cfg = resolve_codeql_config("java")
        if cfg.binary and Path(cfg.binary).is_file():
            engines["codeql"] = cfg.binary
        detail = codeql_status("java")
        engine_details["codeql"] = {
            "found": detail["found"], "version": detail["version"],
            "binary": detail["binary"], "search_path": detail["search_path"],
            "suite": detail["suite"], "build_mode": detail["build_mode"],
        }
    except Exception:  # noqa: BLE001, S110
        pass
    return {
        "db": db,
        "profiles": {"count": len(list_profiles())},
        "docker": docker_info,
        "engines": engines,
        "engine_details": engine_details,
        "queue": queue,
    }


@app.post("/api/scans/{scan_id}/promote")
async def promote_scan(scan_id: int) -> dict:
    from codesentry.rag.experience import promote_findings

    return {"ok": True, "promoted": promote_findings(scan_id)}


@app.get("/api/experience/vuln-cases")
async def experience_vuln_cases(q: str = "", cwe: int | None = None) -> dict:
    from codesentry.rag.experience import search_vuln_cases

    return {"cases": search_vuln_cases(q, cwe=cwe, limit=20)}


@app.get("/api/experience/patterns")
async def experience_patterns(q: str = "", cwe: int | None = None) -> dict:
    from codesentry.rag.experience import search_patterns

    return {"patterns": search_patterns(q, cwe=cwe, limit=20)}


@app.get("/api/scans/{scan_id}/artifacts")
async def get_scan_artifacts(scan_id: int) -> dict:
    from codesentry.orchestrator.artifacts import list_artifacts

    return {"scan_id": scan_id, "artifacts": list_artifacts(scan_id)}


@app.get("/api/scans/{scan_id}/artifacts/verify")
async def verify_scan_artifacts(scan_id: int) -> dict:
    from codesentry.orchestrator.artifacts import verify_chain

    return verify_chain(scan_id)


class AskPayload(BaseModel):
    question: str
    scan_id: int | None = None


class CopilotPayload(BaseModel):
    agent: str
    version: int | None = None


@app.post("/api/assist/copilot")
async def assist_copilot(payload: CopilotPayload) -> dict:
    from codesentry.control.assist import copilot

    try:
        return await run_in_threadpool(copilot, payload.agent, payload.version)
    except Exception as e:
        raise HTTPException(503, f"Copilot 不可用：{str(e)[:200]}") from e


class KbSearchPayload(BaseModel):
    query: str
    top_k: int = 5


class KbImportPayload(BaseModel):
    source: str
    title: str = ""
    content: str
    lang: str = "zh"


@app.get("/api/kb/stats")
async def kb_stats() -> dict:
    from codesentry.rag.kb_ops import stats

    return stats()


@app.post("/api/kb/search")
async def kb_search(payload: KbSearchPayload) -> dict:
    from codesentry.rag.kb_ops import search

    return {"rows": await run_in_threadpool(search, payload.query, payload.top_k)}


@app.post("/api/kb/import")
async def kb_import(payload: KbImportPayload) -> dict:
    from codesentry.rag.kb_ops import import_text

    ok = await run_in_threadpool(
        import_text, payload.source, payload.title, payload.content, payload.lang
    )
    if not ok:
        raise HTTPException(400, "导入失败（内容为空或 DB 不可用）")
    return {"ok": True, "source": payload.source}


class KbPreviewPayload(BaseModel):
    content: str
    size: int = 800


class KbRebuildPayload(BaseModel):
    source: str = ""


@app.get("/api/kb/chunks")
async def kb_chunks(source: str = "", limit: int = 50) -> dict:
    from codesentry.rag.kb_ops import list_chunks

    return {"chunks": await run_in_threadpool(list_chunks, source, limit)}


@app.post("/api/kb/preview")
async def kb_preview(payload: KbPreviewPayload) -> dict:
    from codesentry.rag.kb_ops import preview_chunks

    chunks = await run_in_threadpool(preview_chunks, payload.content, payload.size)
    return {"chunks": chunks, "count": len(chunks)}


@app.post("/api/kb/rebuild")
async def kb_rebuild(payload: KbRebuildPayload) -> dict:
    from codesentry.rag.kb_ops import rebuild

    return await run_in_threadpool(rebuild, payload.source)


@app.delete("/api/kb/source")
async def kb_delete_source(source: str) -> dict:
    from codesentry.rag.kb_ops import delete_source

    return {"ok": True, "deleted": await run_in_threadpool(delete_source, source)}


class CommentPayload(BaseModel):
    body: str
    finding_id: int | None = None
    author: str = ""


@app.get("/api/scans/{scan_id}/tools")
async def list_scan_tools(scan_id: int) -> dict:
    from codesentry.control.tool_gateway import list_runs, list_tools

    return {"scan_id": scan_id, "tools": list_tools(), "runs": list_runs(scan_id)}


@app.post("/api/scans/{scan_id}/tools/{tool}")
async def run_scan_tool(scan_id: int, tool: str) -> dict:
    from codesentry.config import get_settings
    from codesentry.control.tool_gateway import run_tool
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT repo_path FROM scans WHERE id=%s", (int(scan_id),))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "scan not found")
    settings = get_settings()
    try:
        return await run_in_threadpool(
            run_tool, scan_id, tool, str(row[0]),
            allow_network=settings.tool_allow_network,
            timeout_s=settings.tool_timeout_s,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/scans/{scan_id}/function")
async def extract_scan_function(scan_id: int, path: str, line: int = 1) -> dict:
    from codesentry.control.harness_templates import extract_function

    try:
        return await run_in_threadpool(extract_function, scan_id, path, line)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@app.post("/api/findings/{finding_id}/verify")
async def verify_finding_harness(finding_id: int) -> dict:
    from codesentry.control.harness import verify_finding

    try:
        return await run_in_threadpool(verify_finding, finding_id)
    except ValueError as e:
        raise HTTPException(404 if "not found" in str(e) else 400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e


@app.get("/api/scans/{scan_id}/verifications")
async def list_verifications(scan_id: int, finding_id: int | None = None) -> dict:
    from codesentry.control.harness import list_runs

    return {"scan_id": scan_id, "runs": list_runs(scan_id, finding_id)}


@app.post("/api/findings/{finding_id}/fix")
async def generate_finding_fix(finding_id: int) -> dict:
    from pathlib import Path

    from codesentry.agents.fix_agent import generate_fix
    from codesentry.agents.runtime import prepare_agent
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT f.scan_id, f.rule_id, f.cwe, f.severity, f.file, f.line, f.message,"
            " s.repo_path FROM findings f JOIN scans s ON s.id=f.scan_id WHERE f.id=%s",
            (int(finding_id),),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "finding not found")
    scan_id, rule_id, cwe, severity, rel, line, message, repo = row
    repo_path = Path(str(repo)).resolve()
    target = (repo_path / str(rel)).resolve()
    if repo_path not in target.parents and target != repo_path:
        raise HTTPException(400, "finding file outside repo")
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        raise HTTPException(404, f"源码不可读：{e}") from e
    start = max(1, int(line or 1) - 40)
    end = min(len(lines), int(line or 1) + 40)
    source = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))
    runtime = await run_in_threadpool(prepare_agent, "audit", scan_id=int(scan_id),
                                      with_llm=True)
    if runtime is None or runtime.llm is None:
        raise HTTPException(503, "LLM 未配置，无法生成修复建议")
    finding = {"rule_id": rule_id, "cwe": cwe, "severity": severity,
               "file": rel, "line": line, "message": message}
    try:
        out = await run_in_threadpool(generate_fix, runtime.llm, finding, source, {})
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE findings SET fix_patch=%s, fix_summary=%s, fix_tests=%s::jsonb"
            " WHERE id=%s",
            (out["patch"], out["summary"], __import__("json").dumps(out["tests"]),
             int(finding_id)),
        )
        conn.commit()
    try:
        from codesentry.control.audit import audit_write

        audit_write("api", "generate", "finding_fix", str(finding_id), None,
                    {"summary": out["summary"]})
    except Exception:  # noqa: BLE001, S110
        pass
    return {"finding_id": finding_id, **out}


@app.get("/api/scans/{scan_id}/comments")
async def scan_comments(scan_id: int, finding_id: int | None = None) -> dict:
    from codesentry.control.review_comments import list_comments

    return {"comments": list_comments(scan_id, finding_id)}


@app.post("/api/scans/{scan_id}/comments")
async def add_scan_comment(scan_id: int, payload: CommentPayload) -> dict:
    from codesentry.control.review_comments import add_comment

    try:
        out = add_comment(scan_id, payload.body, finding_id=payload.finding_id,
                          author=payload.author)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if out is None:
        raise HTTPException(503, "评论写入失败")
    return out


@app.post("/api/assist/ask")
async def assist_ask(payload: AskPayload) -> dict:
    from codesentry.control.assist import ask

    try:
        return await run_in_threadpool(ask, payload.question, payload.scan_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(503, f"AI 辅助不可用：{str(e)[:200]}") from e


class RetentionPayload(BaseModel):
    days: int = 30


@app.post("/api/ops/retention")
async def purge_retention(payload: RetentionPayload) -> dict:
    from codesentry.control.retention import purge_scans

    return {"ok": True, "deleted": await run_in_threadpool(purge_scans, payload.days)}


@app.get("/api/ops/disk")
async def ops_disk() -> dict:
    from codesentry.control.retention import disk_usage

    return await run_in_threadpool(disk_usage)


class MaintenancePayload(BaseModel):
    days: int = 30
    codeql_days: int = 7
    orphan_days: int = 7
    clean_images: bool = False


@app.post("/api/ops/maintenance")
async def ops_maintenance(payload: MaintenancePayload) -> dict:
    from codesentry.control.retention import run_maintenance

    return await run_in_threadpool(
        run_maintenance, days=payload.days, codeql_days=payload.codeql_days,
        orphan_days=payload.orphan_days, clean_images=payload.clean_images,
    )


@app.get("/api/health")
async def health() -> dict:
    return await run_in_threadpool(_health_sync)


@app.get("/api/engines/codeql/status")
async def codeql_status() -> dict:
    from codesentry.control.engine_config import codeql_status as _status

    return await run_in_threadpool(_status, "java")


class CodeQLInstallPayload(BaseModel):
    version: str = ""
    license_ack: bool = False
    sha256: str = ""


@app.get("/api/engines/codeql/install/status")
async def codeql_install_status() -> dict:
    from codesentry.config import get_settings
    from codesentry.control.engine_config import codeql_status
    from codesentry.control.engine_install import install_dir

    s = get_settings()
    status = await run_in_threadpool(codeql_status)
    return {**status, "install_dir": str(install_dir()),
            "auto_install": s.codeql_auto_install,
            "license_ack": s.codeql_license_ack,
            "target_version": s.codeql_version}


@app.post("/api/engines/codeql/install")
async def codeql_install(payload: CodeQLInstallPayload) -> dict:
    from codesentry.control.engine_install import install_codeql

    return await run_in_threadpool(
        install_codeql, version=payload.version, license_ack=payload.license_ack,
        sha256=payload.sha256,
    )


@app.post("/api/engines/codeql/test")
async def codeql_test() -> dict:
    from codesentry.control.engine_config import codeql_status as _status

    result = await run_in_threadpool(_status, "java")
    return {**result, "ok": bool(result.get("found"))}
