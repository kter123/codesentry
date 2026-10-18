"""引擎私有条目 → 统一 Finding（agent.md FR-2）。"""

import re

from codesentry.models import Finding, Severity

# semgrep severity（官方大小写）→ 统一 severity
_SEMGREP_SEV: dict[str, Severity] = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}

# 引擎置信度初值（M1 固定；M3 由 Triage 调整）
_ENGINE_CONFIDENCE = {"semgrep": 0.5, "joern": 0.7, "codeql": 0.7}

_CWE_RE = re.compile(r"CWE-(\d+)")
_CWE_FALLBACK = 610  # 缺失映射显式标注为 CWE-610（无主类缺失）


def _extract_cwe(cwe_text: str) -> int:
    m = _CWE_RE.search(cwe_text or "")
    return int(m.group(1)) if m else _CWE_FALLBACK


def normalize_semgrep(doc: dict) -> list[Finding]:
    out: list[Finding] = []
    for r in doc.get("results", []):
        extra = r.get("extra", {})
        raw_sev = str((extra.get("severity") or "")).upper()
        cwe_meta = (extra.get("metadata") or {}).get("cwe") or ""
        sev = _SEMGREP_SEV.get(raw_sev, "low")
        out.append(
            Finding(
                rule_id=r.get("check_id") or "unknown",
                cwe=_extract_cwe(str(cwe_meta)),
                severity=sev,
                confidence=_ENGINE_CONFIDENCE["semgrep"],
                file=r.get("path") or "",
                line=(r.get("start") or {}).get("line") or 1,
                end_line=(r.get("end") or {}).get("line"),
                message=extra.get("message") or "",
                engine="semgrep",
            )
        )
    return out
