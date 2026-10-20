import os
import stat

import pytest

from codesentry.security import secrets as sec


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("CODESENTRY_WORK_DIR", str(tmp_path))
    monkeypatch.setenv("CODESENTRY_SECRET_KEY", "unit-test-secret")
    monkeypatch.setattr(sec, "_key_file", lambda: tmp_path / ".secret_key")


def test_encrypt_roundtrip():
    token = sec.encrypt_secret("sk-abcdef123456")
    assert token and token != "sk-abcdef123456"
    assert sec.decrypt_secret(token) == "sk-abcdef123456"


def test_empty_roundtrip():
    assert sec.encrypt_secret("") == ""
    assert sec.decrypt_secret("") == ""
    assert sec.mask_secret("") == ""


def test_mask():
    assert sec.mask_secret("sk-1234567890") == "sk-12345…"
    assert sec.mask_secret("short") == "***"
    assert sec.mask_cipher(sec.encrypt_secret("sk-1234567890")) == "sk-12345…"


def test_redact_mapping():
    data = {"name": "x", "api_key": "sk-secret", "nested": {"password": "p", "ok": 1}}
    out = sec.redact_mapping(data)
    assert out["name"] == "x"
    assert out["api_key"] == "***"
    assert out["nested"]["password"] == "***"
    assert out["nested"]["ok"] == 1


def test_generated_key_file_permissions(monkeypatch, tmp_path):
    monkeypatch.delenv("CODESENTRY_SECRET_KEY", raising=False)
    monkeypatch.setenv("CODESENTRY_WORK_DIR", str(tmp_path))
    monkeypatch.setattr(sec, "_key_file", lambda: tmp_path / ".secret_key")
    f = sec.get_fernet()
    token = f.encrypt(b"x")
    assert f.decrypt(token) == b"x"
    p = tmp_path / ".secret_key"
    assert p.exists()
    if os.name == "posix":
        assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_decrypt_invalid_raises_without_cipher():
    with pytest.raises(sec.SecretError) as ei:
        sec.decrypt_secret("not-a-token")
    assert "not-a-token" not in str(ei.value)
