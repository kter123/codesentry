"""PoCGenAgent（agent.md FR-13/FR-14，D27–D32）。

M6.1：支持 AgentRuntime 注入（生效 Prompt + Skills + 能力矩阵）；
POC_RUN=off（默认）→ plausible；sandbox 才执行；危险 payload 静态拒绝。
"""

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

DANGEROUS_PATTERNS = [
    (re.compile(r"\brm\s+-rf\b|\bdel\s+/[sq]\b"), "递归删除命令"),
    (re.compile(r"\bsudo\b"), "提权命令"),
    (re.compile(r"\bnc\b\s|\bncat\b|\bbash\s+-i\b.*\b/dev/tcp\b|/dev/tcp/"), "反弹 shell"),
    (re.compile(r"\bcurl\b.*\|\s*(ba)?sh\b|\bwget\b.*\|\s*(ba)?sh\b"), "管道执行"),
    (re.compile(r".shutdown|fork\(\)|while\s+true.*fork"), "拒绝服务模式"),
    (re.compile(r"\bos\.remove\b|\bshutil\.rmtree\b|\bos\.unlink\b"), "文件删除模式"),
]

HTTP_CWES = {918, 79, 89, 611, 352, 77, 113}
POC_VERDICTS = ("verified", "plausible", "false_positive")

_DEFAULT_SYSTEM = (
    "你是 PoCGenAgent。基于 finding 与证据生成：①利用链路步骤列表（source→传播→sink）；"
    "②可执行的内容——HTTP 类给 curl 命令序列；本地类给 python/注入点调用样例。"
    "禁止生成 rm -rf / 反弹 shell / sudo 等 payload。"
    "验证占位符：HTTP 回调使用 {CANARY_URL}，命令回显使用 {CANARY_CMD}，文件副作用使用 {CANARY_FILE}。"
    '只输出 JSON：{"exploit_chain": ["step1", ...], "poc_script": "...", "notes": "备注"}'
)


def check_payload_safety(poc_script: str) -> tuple[bool, str]:
    for pat, msg in DANGEROUS_PATTERNS:
        if pat.search(poc_script):
            return False, f"危险 payload 拒绝：{msg}"
    return True, ""


def gen_poc(llm, finding: dict, evidence: dict, system: str | None = None,
            tools=None, max_iterations: int = 8) -> dict:
    cwe = int(finding.get("cwe") or 0)
    kind = "http" if cwe in HTTP_CWES else "local"
    user = json.dumps({"finding": finding, "evidence": evidence}, ensure_ascii=False)[:10000]
    if system and "poc_script" not in system:
        system = system.rstrip() + "\n\n" + _DEFAULT_SYSTEM
    system = system or _DEFAULT_SYSTEM
    try:
        if tools:
            from codesentry.agents.tools import run_tool_loop

            text, trace = run_tool_loop(
                llm, system, user, tools=tools, max_iterations=max_iterations, model_role="deep"
            )
        else:
            text = llm.complete(system, user, model_role="deep")
            trace = []
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            d = json.loads(m.group(0))
            chain = d.get("exploit_chain") or []
            script = str(d.get("poc_script") or "")
            safe, reason = check_payload_safety(script)
            if not safe:
                return {"exploit_chain": chain, "poc_script": "", "poc_kind": kind,
                        "notes": reason, "rejected": True, "tool_trace": trace}
            return {"exploit_chain": chain, "poc_script": script, "poc_kind": kind,
                    "notes": d.get("notes", ""), "rejected": False, "tool_trace": trace}
        return {"exploit_chain": [], "poc_script": "", "poc_kind": kind,
                "notes": "LLM 输出不可解析", "rejected": False, "tool_trace": trace}
    except Exception as e:  # noqa: BLE001 - 生成失败 → finding 保留 + plausible + 原因（§10）
        return {"exploit_chain": [], "poc_script": "", "poc_kind": kind,
                "notes": f"生成失败：{str(e)[:80]}", "rejected": False, "tool_trace": []}


def execute_poc_local(poc_script: str, work_dir: str, timeout: int = 60) -> dict:
    safe, reason = check_payload_safety(poc_script)
    if not safe:
        return {"executed": False, "log": reason, "success": False}
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "poc.py"
        p.write_text(poc_script, encoding="utf-8")
        try:
            r = subprocess.run(
                ["python3", str(p)], capture_output=True, text=True, timeout=timeout,
                check=False, cwd=td,
            )
            return {
                "executed": True,
                "log": (r.stdout + r.stderr)[-4000:],
                "success": r.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            return {"executed": True, "log": f"timeout after {timeout}s", "success": False}


def _merge_messages(state: dict, runtime) -> list:
    existing = list(state.get("messages") or [])
    if runtime is not None:
        existing.extend(f"{runtime.agent}: {w}" for w in runtime.warnings)
    return existing


def _snapshot_updates(state: dict, runtime) -> dict:
    if runtime is None:
        return {}
    out: dict = {}
    pv = {**(state.get("prompt_versions") or {}), **runtime.prompt_snapshot()}
    if pv:
        out["prompt_versions"] = pv
    ss = {**(state.get("skills_snapshot") or {}), **runtime.skills_snapshot()}
    if ss:
        out["skills_snapshot"] = ss
    return out


def run_poc_gen(state: dict, llm=None, runtime=None) -> dict:
    """节点签名：state -> update。POC_RUN 默认 off → 全 plausible（D28/§10）。"""
    from codesentry.config import get_settings

    triaged = state.get("triaged_findings") or []
    messages = _merge_messages(state, runtime)

    if runtime is not None and not runtime.enabled:
        disabled_results: dict[str, dict] = {}
        disabled_updated: list[dict] = []
        for t in triaged:
            fdict = {k: v for k, v in t.items() if k != "triage"}
            key = f"{fdict.get('rule_id')}@{fdict.get('line')}"
            disabled_results[key] = {
                "exploit_chain": [], "poc_file": "", "verdict": "plausible",
                "execution_log": "agent disabled——PoC 不生成，最高 plausible",
            }
            disabled_updated.append({**t, "poc": disabled_results[key]})
        return {"poc_results": disabled_results, "triaged_findings": disabled_updated,
                "phase": "human_review", "messages": messages,
                **_snapshot_updates(state, runtime)}

    mode = os.environ.get("CODESENTRY_POC_RUN") or get_settings().poc_run
    if runtime is not None:
        llm = runtime.llm or llm
        if not runtime.capabilities.get("poc_exec", True):
            mode = "off"

    system = runtime.system() if runtime is not None else None
    try:
        from codesentry.agents.tools import build_tools

        tools = build_tools(state)
    except Exception:  # noqa: BLE001
        tools = {}
    max_iterations = int(getattr(runtime, "max_iterations", 8) or 8)
    work = Path(get_settings().work_dir)
    poc_results: dict[str, dict] = {}
    updated: list[dict] = []
    for t in triaged:
        fdict = {k: v for k, v in t.items() if k != "triage"}
        key = f"{fdict.get('rule_id')}@{fdict.get('line')}"
        if mode == "off":
            poc_results[key] = {
                "exploit_chain": [], "poc_file": "", "verdict": "plausible",
                "execution_log": "POC_RUN=off（或能力矩阵禁用 poc_exec）— 只生成不执行（D28）",
            }
            updated.append({**t, "poc": poc_results[key]})
            continue
        gen = gen_poc(
            llm, fdict, (state.get("evidence") or {}).get(key, {}),
            system=system, tools=tools, max_iterations=max_iterations,
        ) if llm else {"exploit_chain": [], "poc_script": "", "poc_kind": "local",
                       "notes": "no llm", "rejected": False, "tool_trace": []}
        script = str(gen.get("poc_script") or "")
        if gen.get("rejected"):
            poc_results[key] = {"exploit_chain": gen["exploit_chain"], "poc_file": "",
                                "verdict": "plausible", "execution_log": gen["notes"],
                                "tool_trace": gen.get("tool_trace", [])}
            updated.append({**t, "poc": poc_results[key]})
            continue
        if not script:
            poc_results[key] = {"exploit_chain": gen["exploit_chain"], "poc_file": "",
                                "verdict": "plausible",
                                "execution_log": f"生成失败：{gen['notes']}",
                                "tool_trace": gen.get("tool_trace", [])}
            updated.append({**t, "poc": poc_results[key]})
            continue
        poc_dir = work / "poc"
        poc_dir.mkdir(parents=True, exist_ok=True)
        fname = f"poc_{re.sub(r'[^A-Za-z0-9]', '_', key)[:60]}.py"
        poc_file = str(poc_dir / fname)
        Path(poc_file).write_text(script, encoding="utf-8")
        method = "none"
        nonce = ""
        if mode == "sandbox":
            target_url = str(state.get("target_url") or "")
            if target_url or state.get("deploy_status") == "ready":
                from codesentry.sandbox.verify import verify_poc

                vr = verify_poc(
                    int(state.get("scan_id") or 0), script, target_url,
                    f"codesentry-target-{state.get('scan_id')}",
                )
                verdict = "verified" if vr.ok else "plausible"
                log = vr.log
                method = vr.method
                nonce = vr.nonce
            else:
                ex = execute_poc_local(script, str(poc_dir))
                verdict = "verified" if ex["success"] else "plausible"
                log = ex["log"]
        else:
            verdict = "plausible"
            log = "POC_RUN=target — 目标环境待用户显式授权（本轮不支持远程 target）"
        poc_results[key] = {
            "exploit_chain": gen["exploit_chain"], "poc_file": poc_file,
            "verdict": verdict, "execution_log": log,
            "verification_method": method, "verification_nonce": nonce,
            "tool_trace": gen.get("tool_trace", []),
        }
        updated.append({**t, "poc": poc_results[key]})
    return {"poc_results": poc_results, "triaged_findings": updated,
            "phase": "human_review", "messages": messages,
            **_snapshot_updates(state, runtime)}
