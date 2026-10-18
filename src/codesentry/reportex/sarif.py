"""SARIF 2.1.0 导出（agent.md FR-6）。"""

import json
from pathlib import Path

from codesentry.models import Finding

_SEV_TO_LEVEL = {"critical": "error", "high": "error", "medium": "warning", "low": "note", "info": "note"}


def _rule_key(f: Finding) -> str:
    return f.rule_id


def findings_to_sarif(findings: list[Finding]) -> dict:
    rules: dict[str, dict] = {}
    results = []
    for f in findings:
        key = _rule_key(f)
        if key not in rules:
            rules[key] = {
                "id": key,
                "shortDescription": {"text": f.message or key},
                "defaultConfiguration": {"level": _SEV_TO_LEVEL[f.severity]},
            }
        prop_block = {
            "confidence": f.confidence,
            "severity": f.severity,
            "cwe": f.cwe,
            "engine": f.engine,
        }
        results.append(
            {
                "ruleId": key,
                "ruleIndex": list(rules).index(key),
                "level": _SEV_TO_LEVEL[f.severity],
                "message": {"text": f.message},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": f.file},
                            "region": {"startLine": f.line},
                        }
                    }
                ],
                "properties": prop_block,
            }
        )
    return {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "CodeSentry",
                        "informationUri": "https://github.com/kter123/codesentry",
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
            }
        ],
    }


def write_sarif(findings: list[Finding], path: str) -> None:
    doc = findings_to_sarif(findings)
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
