import json
import pathlib

from codesentry.engines.normalize import normalize_semgrep

FIXTURE = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "semgrep_sample.json").read_text()
)


def test_normalize_semgrep_finding_fields():
    fs = normalize_semgrep(FIXTURE)
    assert len(fs) >= 1
    f = fs[0]
    assert f.engine == "semgrep"
    assert f.severity in ("info", "low", "medium", "high", "critical")
    assert 0.0 <= f.confidence <= 1.0
    assert f.file and f.line >= 1


def test_severity_mapping():
    fs = normalize_semgrep(FIXTURE)
    by_sev = {f.rule_id: f.severity for f in fs}
    assert by_sev.get("test-rule-low") == "medium"
    assert by_sev.get("test-rule-high") == "high"


def test_cwe_extraction():
    fs = normalize_semgrep(FIXTURE)
    assert fs[0].cwe == 918
    assert fs[1].cwe == 78
