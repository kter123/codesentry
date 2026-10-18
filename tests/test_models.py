import pytest
from pydantic import ValidationError

from codesentry.models import EngineResult, Finding, LicenseDeclaration, ScanProfile


def test_finding_minimal():
    f = Finding(
        rule_id="py/ssrf", cwe=918, severity="high", confidence=0.7,
        file="a.py", line=10, message="SSRF sink", engine="semgrep",
    )
    assert f.cwe == 918 and f.engine == "semgrep"


def test_finding_severity_enum():
    with pytest.raises(ValidationError):
        Finding(rule_id="x", cwe=79, severity="catastrophe", confidence=0.5,
                file="a", line=1, message="m", engine="semgrep")


def test_finding_optional_fields():
    f = Finding(rule_id="x", cwe=79, severity="low", confidence=0.5,
                file="a", line=1, message="m", engine="joern",
                end_line=5, taint_metadata={"source": "input()"})
    assert f.end_line == 5


def test_license_declaration():
    d = LicenseDeclaration(OSS=True, declared_at="2026-10-18T00:00:00Z")
    assert d.OSS is True


def test_engine_result_degraded():
    r = EngineResult(engine="codeql", status="unavailable", reason="license gate")
    assert r.status == "unavailable" and r.findings == []
