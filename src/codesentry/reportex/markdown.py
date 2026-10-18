"""中文 Markdown 报告（agent.md FR-6）。"""

from collections import Counter

from codesentry.models import Finding

_SEV_ORDER = ["critical", "high", "medium", "low", "info"]
_SEV_CN = {"critical": "严重", "high": "高危", "medium": "中危", "low": "低危", "info": "信息"}
_ENGINE_CN = {"codeql": "CodeQL", "joern": "Joern", "semgrep": "Semgrep"}


def render_markdown(
    findings: list[Finding],
    profile_languages: list[str],
    license_declaration: dict[str, str | bool] | None = None,
) -> str:
    lines: list[str] = []
    lines.append("# CodeSentry 安全审计报告")
    lines.append("")
    lines.append("## 概览")
    lines.append("")
    lines.append(f"- 语言：{', '.join(profile_languages) if profile_languages else '未知'}")
    if license_declaration:
        lic = "开源" if license_declaration.get("OSS") else "闭源（proprietary）"
        lines.append(f"- 许可声明：{lic} @ {license_declaration.get('declared_at', '')}")
    counts: Counter[str] = Counter(f.severity for f in findings)
    summary = ", ".join(
        f"{_SEV_CN[s]} {counts[s]}" for s in _SEV_ORDER if s in counts
    )
    lines.append(f"- 发现：共 {len(findings)} 条（{summary or '无'}）")
    lines.append("")
    lines.append("## Finding 明细")
    lines.append("")
    if not findings:
        lines.append("**未发现漏洞。**")
        lines.append("")
        return "\n".join(lines)
    for i, f in enumerate(findings, 1):
        lines.append(f"### {i}. {f.rule_id}（{_SEV_CN[f.severity]}）")
        lines.append("")
        lines.append(f"- 位置：`{f.file}:{f.line}`")
        lines.append(f"- CWE：CWE-{f.cwe}")
        lines.append(f"- 引擎：{_ENGINE_CN.get(f.engine, f.engine)}；置信度：{f.confidence:.2f}")
        lines.append(f"- 消息：{f.message}")
        lines.append("- 修复建议：（M3 由 TriageAgent 补全）")
        lines.append("")
    return "\n".join(lines)
