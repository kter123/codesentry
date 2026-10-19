"""M5.1 WebUI 骨架单测：不依赖 LLM 的基本接口。"""

import io
import os
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SRC = str(Path(__file__).resolve().parent.parent / "src")
if SRC not in "".__class__.__module__:
    pass

os.environ.setdefault("CODESENTRY_DATABASE_URL", "postgresql://codesentry:devtest@127.0.0.1:5432/codesentry")

from codesentry.web.server import app

client = TestClient(app)


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("proj/app.py", "x = 1\n")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _work_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESENTRY_WORK_DIR", str(tmp_path / "work"))


def test_root():
    r = client.get("/")
    assert r.status_code == 200 and r.json()["service"] == "codesentry-webui"


def test_upload_requires_payload():
    r = client.post("/api/scans")
    assert r.status_code == 400


def test_upload_rejects_bad_archive():
    r = client.post("/api/scans", files={"file": ("evil.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400


def test_upload_zip_traversal_rejected(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../evil.py", "x")
    r = client.post("/api/scans", files={"file": ("bad.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 400


def test_diff_text_creates_scan(tmp_path):
    r = client.post("/api/scans", data={"diff_text": "--- a\n+++ b\n@@ x = 1"})
    assert r.status_code == 200, r.text
    assert r.json()["scan_id"] >= 0


def test_list_scans_shows_scan():
    client.post("/api/scans", data={"diff_text": "--- a\n+++ b\n@@ x"})
    r = client.get("/api/scans")
    assert r.status_code == 200 and len(r.json()) >= 1


def test_git_url_https_required():
    r = client.post("/api/scans", data={"git_url": "http://insecure/repo"})
    assert r.status_code == 400


def test_settings_llm_masked():
    r = client.get("/api/settings/llm")
    assert r.status_code == 200
    body = r.json()
    assert "model_api_key" in body
    if body["model_api_key"]:
        assert len(body["model_api_key"]) <= 10  # 掩码：≤8 字符+省略号


def test_settings_unknown_key_rejected():
    r = client.put("/api/settings/llm", json={"values": {"evil_key": "x"}})
    assert r.status_code == 400


def test_settings_discoverable():
    r = client.put("/api/settings/llm", json={"values": {"fast_model": "fx"}})
    assert r.status_code == 200
