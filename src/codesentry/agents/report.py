"""ReportAgent（§7.2）：M1 报告层复用 + triage 结论/修复建议/快照 meta。"""

import json
from itertools import pairwise
from pathlib import Path

from codesentry.models import Finding
from codesentry.reportex.markdown import render_markdown
from codesentry.reportex.sarif import write_sarif


def _short(key: str) -> str:
    text = str(key or "?")
    for prefix in ("endpoint:", "route:", "function:", "method:", "sink:", "source:"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return text.replace("|", "/").replace('"', "'")[:60]


def _path_section(scan_id: int) -> str:
    if not scan_id:
        return "\n## 攻击路径\n\n无路径数据（扫描未落库或为离线报告）。\n"
    try:
        from codesentry.control.audit_paths import list_paths

        paths = list_paths(scan_id, limit=50)
    except Exception:  # noqa: BLE001
        paths = []
    if not paths:
        return "\n## 攻击路径\n\n无路径数据。\n"
    lines = ["", "## 攻击路径", "",
             "| # | 入口 | Sink | 可行性 | 分数 | 状态 | 轮次 | Finding |",
             "|---|---|---|---|---|---|---|---|"]
    for p in paths:
        lines.append(
            f"| {p.get('id')} | `{_short(str(p.get('entry_key') or ''))}` | `{_short(str(p.get('sink_key') or ''))}`"
            f" | {p.get('feasibility')} | {p.get('score')} | {p.get('status')}"
            f" | {p.get('round')} | {p.get('finding_id') or '—'} |"
        )
    lines.extend(["", "### 路径拓扑", ""])
    for p in paths[:10]:
        nodes = [str(n) for n in (p.get("nodes") or [])]
        if not nodes:
            continue
        lines.append(f"**Path #{p.get('id')}**（{p.get('feasibility')}）")
        lines.append("")
        lines.append("```mermaid")
        lines.append("flowchart LR")
        ids = {node: f"n{i}" for i, node in enumerate(nodes)}
        for node, nid in ids.items():
            lines.append(f'  {nid}["{_short(node)}"]')
        for edge in p.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            src, dst = str(edge.get("from") or ""), str(edge.get("to") or "")
            if src in ids and dst in ids:
                lines.append(f"  {ids[src]} -->|{edge.get('kind', '')}| {ids[dst]}")
        # 没有边时按节点顺序连一条视觉链
        if not any(isinstance(e, dict) and e.get("from") in ids and e.get("to") in ids
                   for e in (p.get("edges") or [])):
            ordered = list(ids.values())
            for a, b in pairwise(ordered):
                lines.append(f"  {a} --> {b}")
        lines.extend(["```", ""])
    return "\n".join(lines)


def run_report(state: dict, out_dir: str) -> dict:
    triaged = state.get("triaged_findings") or []
    findings = []
    for t in triaged:
        t_f = {k: v for k, v in t.items() if k in {"rule_id", "cwe", "severity", "confidence", "file", "line", "end_line", "message", "engine", "taint_metadata", "fix_advice"}}
        try:
            findings.append(Finding(**t_f))
        except Exception:  # noqa: BLE001, S112 - 单条坏数据不影响整报
            continue
    p = Path(out_dir)
    p.mkdir(parents=True, exist_ok=True)
    write_sarif(findings, str(p / "report.sarif"))
    md = render_markdown(
        findings,
        profile_languages=(state.get("profile") or {}).get("languages", []),
        license_declaration=state.get("license_declaration"),
    )
    # triage 结论附加段（修复建议 + 未验证标记）
    extra = ["", "## 引擎与图增量", ""]
    for meta in state.get("engine_results_meta") or []:
        if not isinstance(meta, dict):
            continue
        extra.append(
            f"- {meta.get('engine')}/{meta.get('lang') or '—'}：status={meta.get('status')}，"
            f"findings={len(meta.get('findings') or [])}，reason={str(meta.get('reason') or '')[:160]}"
        )
    engine_graph = (state.get("graph_delta") or {}).get("engine_graph") or {}
    if engine_graph:
        extra.append(f"- graph_delta：`{json.dumps(engine_graph, ensure_ascii=False)[:1200]}`")
    extra.extend(["", "## Triage 结论", ""])
    for t in triaged:
        tri = t.get("triage") or {}
        extra.append(f"- `{t.get('rule_id')}@{t.get('line')}`：verdict={tri.get('verdict')}，置信度 {tri.get('confidence')}，理由：{tri.get('rationale')}；修复：{tri.get('fix_advice')}")
    extra_block = "\n".join(extra)
    path_block = _path_section(int(state.get("scan_id") or 0))
    (p / "report.md").write_text(md + path_block + "\n" + extra_block + "\n", encoding="utf-8")
    # 复现快照（NFR-2）
    (p / "snapshot.json").write_text(
        json.dumps({"prompt_versions": state.get("prompt_versions"), "skills_snapshot": state.get("skills_snapshot"),
                    "license_declaration": state.get("license_declaration"), "budget": state.get("budget")},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"phase": "done"}
