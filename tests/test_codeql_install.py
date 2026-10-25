import hashlib
import io
import tarfile
from typing import ClassVar

from codesentry.control import engine_install


class _Resp:
    status_code = 200
    headers: ClassVar[dict] = {}

    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_bytes(self):
        yield self.data


def _bundle(tmp_path) -> bytes:
    src = tmp_path / "src"
    src.mkdir()
    binary = src / "codeql"
    binary.write_text("#!/bin/sh\necho 'CodeQL command-line toolchain release 2.27.2.'\n")
    binary.chmod(0o755)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(binary, arcname="codeql-bundle/codeql")
    return buf.getvalue()


def test_install_requires_license_ack(tmp_path):
    out = engine_install.install_codeql(version="2.27.2", license_ack=False)
    assert out["ok"] is False
    assert "license" in out["error"].lower() or "许可" in out["error"]


def test_release_url_whitelist():
    assert engine_install.release_url("2.27.2").startswith(
        "https://github.com/github/codeql-action/releases/download/"
    )
    try:
        engine_install.release_url("../../evil")
        raise AssertionError("should reject")
    except ValueError:
        pass


def test_install_success_and_sha(tmp_path, monkeypatch):
    data = _bundle(tmp_path)
    digest = hashlib.sha256(data).hexdigest()
    monkeypatch.setenv("CODESENTRY_CODEQL_INSTALL_DIR", str(tmp_path / "install"))
    monkeypatch.setattr(engine_install.httpx, "stream",
                        lambda *a, **k: _Resp(data))
    monkeypatch.setattr(engine_install.subprocess, "run",
                        lambda *a, **k: type("R", (), {
                            "returncode": 0, "stdout": "CodeQL 2.27.2", "stderr": ""})())
    out = engine_install.install_codeql(version="2.27.2", license_ack=True,
                                        sha256=digest)
    assert out["ok"], out
    assert (tmp_path / "install" / "codeql").is_file()
    assert out["verified_sha256"] is True


def test_install_bad_sha(tmp_path, monkeypatch):
    data = _bundle(tmp_path)
    monkeypatch.setenv("CODESENTRY_CODEQL_INSTALL_DIR", str(tmp_path / "install"))
    monkeypatch.setattr(engine_install.httpx, "stream",
                        lambda *a, **k: _Resp(data))
    out = engine_install.install_codeql(version="2.27.2", license_ack=True,
                                        sha256="0" * 64)
    assert out["ok"] is False
    assert "SHA" in out["error"]
