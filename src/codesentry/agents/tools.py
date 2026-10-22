"""Agent 工具循环（M6.6）：read_source / search_code / read_evidence。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path


def _parse_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def build_tools(state: dict) -> dict[str, Callable]:
    repo = Path(str(state.get("repo_path") or ".")).resolve()

    def read_source(path: str, start: int = 1, end: int = 120) -> str:
        target = (repo / str(path)).resolve()
        if repo not in target.parents and target != repo:
            return "DENIED: path escapes repo"
        try:
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as e:
            return f"ERROR: {e}"
        start = max(1, int(start))
        end = min(len(lines), max(start, int(end)))
        return "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))[:8000]

    def search_code(query: str, top_k: int = 3) -> str:
        try:
            from codesentry.rag.retrieve import hybrid_search

            class _Emb:
                def embed(self, texts):
                    return [[0.0] * 8 for _ in texts]

            rows = hybrid_search("code", str(query), [0.0] * 8, top_k=int(top_k))
            return json.dumps(rows, ensure_ascii=False)[:8000]
        except Exception as e:  # noqa: BLE001
            return f"ERROR: {e}"

    def read_evidence(key: str = "") -> str:
        evd = state.get("evidence") or {}
        if key:
            return json.dumps(evd.get(str(key), {}), ensure_ascii=False)[:8000]
        return json.dumps(evd, ensure_ascii=False)[:8000]

    return {"read_source": read_source, "search_code": search_code, "read_evidence": read_evidence}


def run_tool_loop(
    llm,
    system: str,
    user: str,
    *,
    tools: dict[str, Callable] | None,
    max_iterations: int = 8,
    model_role: str = "deep",
) -> tuple[str, list[dict]]:
    """LLM 可返回 {"tool_calls":[...]} 请求工具；最多 max_iterations 轮。"""
    trace: list[dict] = []
    context = user
    text = ""
    for iteration in range(max(1, int(max_iterations or 1))):
        text = llm.complete(system, context, model_role=model_role)
        data = _parse_json(text)
        calls = (data or {}).get("tool_calls") if isinstance(data, dict) else None
        if not calls or not tools:
            trace.append({"iteration": iteration + 1, "final": True})
            break
        results = []
        for call in list(calls)[:3]:
            if not isinstance(call, dict):
                continue
            name = str(call.get("tool") or "")
            args = call.get("args") or {}
            fn = tools.get(name)
            if fn is None:
                results.append(f"{name}: unknown tool")
                continue
            try:
                out = fn(**args) if isinstance(args, dict) else fn()
            except Exception as e:  # noqa: BLE001
                out = f"ERROR: {e}"
            out_s = str(out)[:4000]
            trace.append({"iteration": iteration + 1, "tool": name, "args": args,
                          "output_preview": out_s[:500]})
            results.append(f"[tool {name}] {out_s}")
        context = user + "\n\n## 工具结果\n" + "\n\n".join(results)
    return text, trace
