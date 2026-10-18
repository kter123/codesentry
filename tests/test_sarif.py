from codesentry.models import Finding
from codesentry.reportex.sarif import findings_to_sarif, write_sarif


def _f(**kw):
    base = {"rule_id": "py/ssrf", "cwe": 918, "severity": "high", "confidence": 0.7,
            "file": "a.py", "line": 10, "message": "SSRF", "engine": "semgrep"}
    base.update(kw)
    return Finding(**base)


def test_sarif_structure():
    doc = findings_to_sarif([_f()])
    assert doc["version"] == "2.1.0"
    assert "$schema" in doc
    run = doc["runs"][0]
    assert run["tool"]["driver"]["name"] == "CodeSentry"
    assert len(run["results"]) == 1
    res = run["results"][0]
    assert res["ruleId"] == "py/ssrf"
    assert res["level"] in ("warning", "error", "note")
    assert res["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "a.py"
    assert res["locations"][0]["physicalLocation"]["region"]["startLine"] == 10


def test_sarif_rules_aggregate():
    doc = findings_to_sarif([_f(), _f(rule_id="py/xss", cwe=79)])
    rules = doc["runs"][0]["tool"]["driver"]["rules"]
    ids = {r["id"] for r in rules}
    assert {"py/ssrf", "py/xss"} <= ids


def test_sarif_confidence_property():
    doc = findings_to_sarif([_f(confidence=0.9)])
    props = doc["runs"][0]["results"][0].get("properties", {})
    assert props.get("confidence") == 0.9


def test_write_sarif(tmp_path):
    p = tmp_path / "report.sarif"
    write_sarif([_f()], str(p))
    doc = json.loads(p.read_text()) if (json := __import__("json")) else None
    assert doc["version"] == "2.1.0"
