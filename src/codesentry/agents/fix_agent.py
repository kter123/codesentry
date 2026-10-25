"""修复建议 Agent（P2）：只生成 unified diff，不修改源码。"""

from __future__ import annotations

import json
import re

_DANGEROUS = [
    (re.compile(r"\brm\s+-rf\b"), "rm -rf"),
    (re.compile(r"\bsudo\b"), "sudo"),
    (re.compile(r"/dev/tcp/|\bnc\b\s+.*\s-e\b|\bbash\s+-i\b"), "反弹/交互 shell"),
    (re.compile(r"\bcurl\b.*\|\s*(ba)?sh\b|\bwget\b.*\|\s*(ba)?sh\b"), "管道执行"),
]

SYSTEM = """你是代码修复 Agent。给定 finding、源码切片和图路径，提出最小修复。
只输出 JSON：
{"summary":"一句修复说明","patch":"--- a/...\\n+++ b/...\\n@@ ...", "tests":["..."],"risk":"..."}
patch 必须是 unified diff，只修改必要行；不要输出 shell 命令，不要删除整文件，
不要引入下载执行/反弹 shell/提权逻辑。不得假装已经应用修改。
"""


def check_patch_safety(patch: str) -> tuple[bool, str]:
    text = str(patch or "")
    if not text.strip():
        return False, "patch 为空"
    if "--- " not in text or "+++ " not in text or "@@" not in text:
        return False, "patch 不是 unified diff"
    for pattern, reason in _DANGEROUS:
        if pattern.search(text):
            return False, f"patch 包含危险模式：{reason}"
    return True, ""


def _parse(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def generate_fix(llm, finding: dict, source: str, graph: dict | None = None) -> dict:
    user = json.dumps({
        "finding": finding,
        "source": str(source)[:16000],
        "graph": graph or {},
    }, ensure_ascii=False)[:20000]
    try:
        text = llm.complete(SYSTEM, user, model_role="deep")
    except Exception as e:
        raise RuntimeError(f"修复生成失败：{str(e)[:160]}") from e
    data = _parse(text)
    patch = str(data.get("patch") or "")
    if not patch:
        fence = re.search(r"```(?:diff)?\s*\n(.*?)```", text, re.DOTALL)
        patch = f"--- a/fix\n+++ b/fix\n{patch}" if fence and "--- " not in fence.group(1) else (
            fence.group(1).strip() if fence else ""
        )
    safe, reason = check_patch_safety(patch)
    if not safe:
        raise ValueError(reason)
    tests = data.get("tests") or []
    return {
        "summary": str(data.get("summary") or "")[:1000],
        "patch": patch[:30000],
        "tests": [str(t)[:500] for t in tests[:20]] if isinstance(tests, list) else [],
        "risk": str(data.get("risk") or "")[:1000],
    }
