from codesentry.models import Finding
from codesentry.reportex.markdown import render_markdown


def _f(**kw):
    base = dict(rule_id="py/ssrf", cwe=918, severity="high", confidence=0.7,
                file="a.py", line=10, message="SSRF sink", engine="semgrep")
    base.update(kw)
    return Finding(**base)


def test_markdown_contains_sections():
    md = render_markdown([_f()], profile_languages=["python"])
    for token in ("# CodeSentry", "python", "py/ssrf", "CWE-918", "a.py:10", "置信度"):
        assert token in md


def test_markdown_empty_findings():
    md = render_markdown([], profile_languages=["python"])
    assert "未发现" in md


def test_markdown_license_metadata():
    md = render_markdown([], profile_languages=["python"],
                         license_declaration={"OSS": False, "declared_at": "t"})
    assert "闭源" in md
