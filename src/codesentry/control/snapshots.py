"""扫描快照（M6.1 NFR-2）：Prompt/Skill/LLM 版本在扫描开始时固定。"""

from __future__ import annotations

import json
from typing import Any


def build_scan_snapshot(scan_id: int | None = None) -> dict[str, dict]:
    from codesentry.agents.prompts import load_prompt
    from codesentry.agents.state import AGENT_NAMES
    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.control.profiles import resolve_profile
    from codesentry.control.prompts import get_version, pick_version
    from codesentry.control.skills import snapshot as skill_snapshot

    if not ensure_control_schema():
        return {"prompt_versions": {}, "skills_snapshot": {}, "llm_snapshot": {}}

    prompts: dict[str, Any] = {}
    skills: dict[str, Any] = {}
    llms: dict[str, Any] = {}
    for agent in AGENT_NAMES:
        version, arm = pick_version(agent, scan_id)
        pv = get_version(agent, version) if version else None
        if pv:
            prompts[agent] = {
                "version": pv["version"],
                "sha256": pv.get("body_sha256", ""),
                "fallback": False,
                "ab_arm": arm,
            }
        else:
            _text, seed_version, fallback = load_prompt(agent)
            prompts[agent] = {"version": seed_version, "sha256": "", "fallback": fallback,
                              "ab_arm": arm}
        items = skill_snapshot(agent)
        skills[agent] = items
        profile, source = resolve_profile(agent)
        if profile is not None:
            llms[agent] = {
                "profile_id": profile.id,
                "provider": profile.provider,
                "protocol": profile.protocol,
                "base_url": profile.base_url,
                "fast_model": profile.fast_model,
                "deep_model": profile.deep_model,
                "temperature": profile.temperature,
                "max_tokens": profile.max_tokens,
                "timeout_s": profile.timeout_s,
                "extra_headers": profile.extra_headers or {},
                "model_protocols": profile.model_protocols or {},
                "input_price_per_1k": profile.input_price_per_1k,
                "output_price_per_1k": profile.output_price_per_1k,
                "billing_mode": profile.billing_mode,
                "source": source,
            }
    return {"prompt_versions": prompts, "skills_snapshot": skills, "llm_snapshot": llms}


def snapshot_json(snapshot: dict) -> tuple[str, str, str]:
    return (
        json.dumps(snapshot.get("prompt_versions", {}), ensure_ascii=False),
        json.dumps(snapshot.get("skills_snapshot", {}), ensure_ascii=False),
        json.dumps(snapshot.get("llm_snapshot", {}), ensure_ascii=False),
    )
