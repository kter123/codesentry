"""ReportAgent（§7.2）：M1 报告层复用 + triage 结论/修复建议/快照 meta。"""

import json
from pathlib import Path

from codesentry.models import Finding
from codesentry.reportex.markdown import render_markdown
from codesentry.reportex.sarif import write_sarif


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
    extra = ["", "## Triage 结论", ""]
    for t in triaged:
        tri = t.get("triage") or {}
        extra.append(f"- `{t.get('rule_id')}@{t.get('line')}`：verdict={tri.get('verdict')}，置信度 {tri.get('confidence')}，理由：{tri.get('rationale')}；修复：{tri.get('fix_advice')}")
    extra_block = "\n".join(extra)
    (p / "report.md").write_text(md + extra_block + "\n", encoding="utf-8")
    # 复现快照（NFR-2）
    (p / "snapshot.json").write_text(
        json.dumps({"prompt_versions": state.get("prompt_versions"), "skills_snapshot": state.get("skills_snapshot"),
                    "license_declaration": state.get("license_declaration"), "budget": state.get("budget")},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"phase": "done"}
