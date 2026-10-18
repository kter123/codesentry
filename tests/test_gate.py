from codesentry.gate import LicenseGate


def test_closed_source_blocks_codeql():
    g = LicenseGate(OSS=False)
    allowed, reason = g.check_engine("codeql")
    assert not allowed
    assert "license" in reason.lower() or "闭源" in reason


def test_oss_allows_codeql():
    g = LicenseGate(OSS=True)
    allowed, _ = g.check_engine("codeql")
    assert allowed


def test_any_engine_unrestricted():
    for engine in ("joern", "semgrep"):
        assert LicenseGate(OSS=False).check_engine(engine)[0] is True
