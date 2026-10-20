"""Agent 运行时上下文（M6.1）：生效 Prompt + Skills + LLM + 能力矩阵。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentRuntime:
    agent: str
    enabled: bool
    llm: Any | None
    system_prompt: str
    prompt_version: int | None
    prompt_fallback: bool
    skills: list[Any] = field(default_factory=list)
    skills_block: str = ""
    warnings: list[str] = field(default_factory=list)
    capabilities: dict = field(default_factory=dict)
    model_role: str = "deep"
    profile_id: int | None = None

    def system(self) -> str:
        if self.skills_block:
            return self.system_prompt + "\n" + self.skills_block
        return self.system_prompt

    def prompt_snapshot(self) -> dict:
        if not self.prompt_version:
            return {}
        return {self.agent: {"version": self.prompt_version}}

    def skills_snapshot(self) -> dict:
        items = []
        for s in self.skills:
            items.append(
                {
                    "name": getattr(s, "name", ""),
                    "version": getattr(s, "version", None),
                    "sha256": getattr(s, "body_sha256", ""),
                }
            )
        return {self.agent: items} if items else {}

    def llm_snapshot(self) -> dict:
        if self.llm is None:
            return {}
        return {
            self.agent: {
                "profile_id": self.profile_id,
                "model": getattr(self.llm, "deep_model", "") if self.model_role == "deep"
                else getattr(self.llm, "fast_model", ""),
                "protocol": getattr(self.llm, "protocol", ""),
                "billing_mode": getattr(self.llm, "billing_mode", ""),
            }
        }

    def state_updates(self) -> dict:
        """合并进节点 update 的增量。"""
        out: dict = {}
        if self.prompt_snapshot():
            out["prompt_versions"] = self.prompt_snapshot()
        if self.skills_snapshot():
            out["skills_snapshot"] = self.skills_snapshot()
        if self.warnings:
            out["messages"] = [f"{self.agent}: {w}" for w in self.warnings]
        return out


def prepare_agent(
    agent: str,
    *,
    scan_id: int = 0,
    role: str | None = None,
    with_llm: bool = True,
    session_id: str | None = None,
    snapshot: dict | None = None,
) -> AgentRuntime:
    from codesentry.agents.prompts import load_prompt
    from codesentry.agents.skills import build_context_block
    from codesentry.config import get_settings
    from codesentry.control.agent_config import effective_capabilities, get_agent_config
    from codesentry.control.skills import load_assigned_skills, load_snapshot_skills

    cfg = get_agent_config(agent)
    enabled = bool(cfg.get("enabled", True))
    warnings: list[str] = []

    prompt = ""
    version: int | None = None
    fallback = True
    prompt_entry = ((snapshot or {}).get("prompt_versions") or {}).get(agent) if snapshot else None
    if prompt_entry and prompt_entry.get("version"):
        from codesentry.control.prompts import get_version

        pv = get_version(agent, int(prompt_entry["version"]))
        if pv:
            prompt, version, fallback = pv["body"], pv["version"], False
        else:
            prompt, version, fallback = load_prompt(agent)
    else:
        prompt, version, fallback = load_prompt(agent)
    if fallback:
        warnings.append("Prompt 回退到代码内种子（DB 无生效版本或不可用）")

    if snapshot is not None and "skills_snapshot" in snapshot:
        snap_skills = (snapshot.get("skills_snapshot") or {}).get(agent) or []
        skills = load_snapshot_skills(snap_skills)
    else:
        skills = load_assigned_skills(agent)
    settings = get_settings()
    block, sk_warnings = build_context_block(
        skills, settings.skill_max_per, settings.skill_max_total
    )
    warnings.extend(sk_warnings)
    capabilities = effective_capabilities(agent)
    role = role or str(cfg.get("model_role") or "deep")

    llm = None
    if enabled and with_llm:
        try:
            from codesentry.agents.llm import LLMClient

            if snapshot is not None:
                llm_entry = (snapshot.get("llm_snapshot") or {}).get(agent) or {}
                pid = llm_entry.get("profile_id")
                if pid:
                    from codesentry.control.profiles import get_profile
                    from codesentry.security.secrets import decrypt_secret

                    profile = get_profile(int(pid))
                    if profile is not None:
                        sid = session_id or f"scan-{scan_id}-{agent}-{profile.id}"
                        headers = {
                            str(k): str(v).replace("${session_id}", sid)
                            for k, v in (llm_entry.get("extra_headers") or {}).items()
                        }
                        temp = cfg.get("temperature_override")
                        if temp is None:
                            temp = float(llm_entry.get("temperature", profile.temperature))
                        llm = LLMClient(
                            base_url=llm_entry.get("base_url") or profile.base_url,
                            api_key=decrypt_secret(profile.api_key_cipher),
                            fast_model=llm_entry.get("fast_model") or profile.fast_model,
                            deep_model=llm_entry.get("deep_model") or profile.deep_model,
                            temperature=float(temp),
                            protocol=llm_entry.get("protocol") or profile.protocol,
                            extra_headers=headers,
                            timeout_s=int(cfg.get("timeout_s") or llm_entry.get("timeout_s")
                                          or profile.timeout_s),
                            max_tokens=int(llm_entry.get("max_tokens") or profile.max_tokens),
                            model_prefix_policy=profile.model_prefix_policy,
                            model_protocols=llm_entry.get("model_protocols") or {},
                            input_price_per_1k=float(
                                llm_entry.get("input_price_per_1k", profile.input_price_per_1k)
                            ),
                            output_price_per_1k=float(
                                llm_entry.get("output_price_per_1k", profile.output_price_per_1k)
                            ),
                            billing_mode=llm_entry.get("billing_mode") or profile.billing_mode,
                            profile_id=profile.id,
                            agent=agent,
                            scan_id=scan_id,
                        )
                if llm is None:
                    llm = LLMClient.from_config()
            else:
                llm = LLMClient.for_agent(
                    agent, role=role, scan_id=scan_id, session_id=session_id,
                    timeout_s=int(cfg.get("timeout_s") or 0) or None,
                    temperature=cfg.get("temperature_override"),
                )
        except Exception as exc:  # noqa: BLE001 - LLM 不可用时节点降级
            warnings.append(f"LLM 不可用：{str(exc)[:120]}")

    return AgentRuntime(
        agent=agent,
        enabled=enabled,
        llm=llm,
        system_prompt=prompt,
        prompt_version=version,
        prompt_fallback=fallback,
        skills=skills,
        skills_block=block,
        warnings=warnings,
        capabilities=capabilities,
        model_role=role,
        profile_id=getattr(llm, "profile_id", None),
    )
