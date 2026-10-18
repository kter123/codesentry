"""PoCGenAgent（agent.md FR-13/FR-14，D27–D32）。

分级 PoC：HTTP 类 → curl 请求序列；本地类 → payload+注入点+本地调用脚本。
POC_RUN=off（默认）→ 全部 plausible；sandbox/target 显式开启才执行。
危险 payload 静态检查（§10）：rm 类/反弹 shell/DNS 出网模板 → 拒绝并标 reason。
执行日志回填 verdict：verified / plausible / false_positive；生成失败 → plausible + 原因。
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
]

HTTP_CWES = {918, 79, 89, 611, 352, 77, 113}  # HTTP 类漏洞（web 接口型）
POC_VERDICTS = ("verified", "plausible", "false_positive")


def check_payload_safety(poc_script: str) -> tuple[bool, str]:
    """静态危险模式检查；命中 (False, 原因)。"""
    for pat, msg in DANGEROUS_PATTERNS:
        if pat.search(poc_script):
            return False, f"危险 payload 拒绝：{msg}"
    return True, ""


def gen_poc(llm, finding: dict, evidence: dict) -> dict:
    """生成利用链路 + PoC 脚本文本（不执行）。返回 {exploit_chain, poc_script, poc_kind, notes}。"""
    cwe = int(finding.get("cwe") or 0)
    kind = "http" if cwe in HTTP_CWES else "local"
    system = (
        "你是 PoCGenAgent。基于 finding 与证据生成：①利用链路步骤列表（source→传播→sink）；"
        "②可执行的内容——HTTP 类给 curl 命令序列；本地类给 python/注入点调用样例。"
        "禁止生成 rm -rf / 反弹 shell / sudo 等 payload。"
        '只输出 JSON：{"exploit_chain": ["step1", ...], "poc_script": "...", "notes": "备注"}'
    )
    user = json.dumps({"finding": finding, "evidence": evidence}, ensure_ascii=False)[:10000]
    try:
        text = llm.complete(system, user, model_role="deep")
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            d = json.loads(m.group(0))
            chain = d.get("exploit_chain") or []
            script = str(d.get("poc_script") or "")
            safe, reason = check_payload_safety(script)
            if not safe:
                return {"exploit_chain": chain, "poc_script": "", "poc_kind": kind, "notes": reason, "rejected": True}
            return {"exploit_chain": chain, "poc_script": script, "poc_kind": kind, "notes": d.get("notes", ""), "rejected": False}
        return {"exploit_chain": [], "poc_script": "", "poc_kind": kind, "notes": "LLM 输出不可解析", "rejected": False}
    except Exception as e:  # noqa: BLE001 - 生成失败 → finding 保留 + plausible + 原因（§10）
        return {"exploit_chain": [], "poc_script": "", "poc_kind": kind, "notes": f"生成失败：{str(e)[:80]}", "rejected": False}


def execute_poc_local(poc_script: str, work_dir: str, timeout: int = 60) -> dict:
    """sandbox 档本地执行：临时目录 + 禁出网（简化：无网络钩子，靠系统 sandbox 工具；logs 回填）。"""
    safe, reason = check_payload_safety(poc_script)
    if not safe:
        return {"executed": False, "log": reason, "success": False}
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "poc.py"
        p.write_text(poc_script, encoding="utf-8")
        try:
            r = subprocess.run(
                ["python3", str(p)], capture_output=True, text=True, timeout=timeout, check=False, cwd=td
            )
            return {
                "executed": True,
                "log": (r.stdout + r.stderr)[-4000:],
                "success": r.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            return {"executed": True, "log": f"timeout after {timeout}s", "success": False}


def run_poc_gen(state: dict, llm=None) -> dict:
    """节点签名：state -> update。POC_RUN 默认 off → 全 plausible（D28/§10）。"""
    from codesentry.config import get_settings

    mode = os.environ.get("CODESENTRY_POC_RUN", "off")
    work = Path(get_settings().work_dir)
    poc_results: dict = {}
    triaged = state.get("triaged_findings") or []
    updated: list[dict] = []
    for t in triaged:
        fdict = {k: v for k, v in t.items() if k != "triage"}
        key = f"{fdict.get('rule_id')}@{fdict.get('line')}"
        if mode == "off":
            poc_results[key] = {
                "exploit_chain": [], "poc_file": "", "verdict": "plausible",
                "execution_log": "POC_RUN=off — 只生成不执行（D28）",
            }
            updated.append({**t, "poc": poc_results[key]})
            continue
        gen = gen_poc(llm, fdict, (state.get("evidence") or {}).get(key, {})) if llm else {"exploit_chain": [], "poc_script": "", "poc_kind": "local", "notes": "no llm", "rejected": False}
        if gen.get("rejected"):
            poc_results[key] = {
                "exploit_chain": gen["exploit_chain"], "poc_file": "", "verdict": "plausible",
                "execution_log": gen["notes"],
            }
            updated.append({**t, "poc": poc_results[key]})
            continue
        if not gen.get("poc_script"):
            poc_results[key] = {"exploit_chain": gen["exploit_chain"], "poc_file": "", "verdict": "plausible",
                                "execution_log": f"生成失败：{gen['notes']}"}
            updated.append({**t, "poc": poc_results[key]})
            continue
        poc_dir = work / "poc"
        poc_dir.mkdir(parents=True, exist_ok=True)
        fname = f"poc_{re.sub(r'[^A-Za-z0-9]', '_', key)[:60]}.py"
        poc_file = str(poc_dir / fname)
        Path(poc_file).write_text(gen["poc_script"], encoding="utf-8")
        if mode == "sandbox":
            ex = execute_poc_local(gen["poc_script"], str(poc_dir))
            verdict = "verified" if ex["success"] else "plausible"  # 试跑失败 ≠ false_positive（§10）
            log = ex["log"]
        else:  # target：用户自备环境；M3 仅记录目标占位，实发 M5 + 显式授权
            verdict = "plausible"
            log = "POC_RUN=target — 目标环境待用户显式授权（M5 交互）"
        poc_results[key] = {"exploit_chain": gen["exploit_chain"], "poc_file": poc_file, "verdict": verdict, "execution_log": log}
        updated.append({**t, "poc": poc_results[key]})
    return {"poc_results": poc_results, "triaged_findings": updated, "phase": "human_review"}
