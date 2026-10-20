"""M5.1 WebUI 骨架单测：不依赖 LLM 的基本接口。"""

import io
import os
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codesentry.db.pool import get_conn

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


def test_upload_ignores_client_filename():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("proj/app.py", "x = 1\n")
    r = client.post(
        "/api/scans",
        files={"file": ("../../evil.zip", buf.getvalue(), "application/zip")},
    )
    assert r.status_code == 200, r.text
    repo = Path(r.json()["repo"])
    assert (repo.parent / "upload.zip").exists()
    assert not (repo.parent / "evil.zip").exists()


def test_git_url_private_host_rejected():
    for url in ("https://127.0.0.1/repo.git", "https://localhost/repo.git", "http://example.com/x"):
        r = client.post("/api/scans", data={"git_url": url})
        assert r.status_code == 400, url


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
    assert client.get("/api/settings/llm").json()["fast_model"] == "fx"


def test_settings_api_key_encrypted_and_masked():
    r = client.put("/api/settings/llm", json={"values": {"model_api_key": "sk-test-123456789"}})
    assert r.status_code == 200
    body = client.get("/api/settings/llm").json()
    assert body["model_api_key"].endswith("…")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT value FROM app_settings WHERE key='model_api_key'")
        stored = cur.fetchone()[0]
    assert "sk-test" not in stored


def test_upload_reuses_scan_row_and_writes_snapshots():
    r = client.post("/api/scans", data={"diff_text": "--- a\n+++ b\n@@ x = 1"})
    assert r.status_code == 200, r.text
    body = r.json()
    sid = body["scan_id"]
    repo = body["repo"]
    deadline = time.time() + 30
    row = None
    while time.time() < deadline:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT status, prompt_snapshot FROM scans WHERE id=%s",
                (sid,),
            )
            row = cur.fetchone()
        if row and row[0] in ("done", "failed"):
            break
        time.sleep(0.2)
    assert row is not None, "scan did not finish in time"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM scans WHERE repo_path=%s", (repo,))
        same_repo = int(cur.fetchone()[0])
    assert same_repo == 1, "upload must not create a duplicate scan row"
    assert isinstance(row[1], dict) and "triage" in row[1]
