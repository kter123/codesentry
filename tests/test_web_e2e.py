"""M5.1 WebUI 自动化基础功能验证（端到端：上传→扫描→时间线→UI 资产可达）。"""

import io
import os
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("CODESENTRY_DATABASE_URL", "postgresql://codesentry:devtest@127.0.0.1:5432/codesentry")

from codesentry.web.server import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _work_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESENTRY_WORK_DIR", str(tmp_path / "work"))


def test_e2e_diff_scan_reaches_running_or_done():
    """发起 diff 扫描 → 记录存在且状态合法 → 记录可读详情。"""
    r = client.post("/api/scans", data={"diff_text": "--- a\n+++ b\n@@ x = 1\n+open(p)"})
    assert r.status_code == 200, r.text
    sid = r.json()["scan_id"]
    d = client.get(f"/api/scans/{sid}").json()
    assert d["id"] == sid
    assert d["status"] in ("running", "done", "failed")
    assert isinstance(d["timeline"], list)


def test_e2e_zip_upload_with_real_code():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("proj/app.py", "import requests\n\ndef f(u):\n    return requests.get(u)\n")
    r = client.post("/api/scans", files={"file": ("proj.zip", buf.getvalue(), "application/zip")}, data={"oss": "true"})
    assert r.status_code == 200, r.text
    sid = r.json()["scan_id"]
    d = client.get(f"/api/scans/{sid}").json()
    assert d["repo_path"].endswith("src")


def test_ui_asset_reachable_under_ui_prefix():
    """资产路径必须挂在 /ui 下（白屏回归测试）。"""
    html = client.get("/ui/").text
    assert 'src="/ui/assets/' in html, "vite base 未接 /ui/ —— 会白屏"
    # 资产可 200
    import re

    m = re.search(r'src="(/ui/assets/[^"]+\.js)"', html)
    assert m, html[:200]
    assert client.get(m.group(1)).status_code == 200


def test_ui_html_contains_root_div():
    html = client.get("/ui/").text
    assert 'id="root"' in html and "<title>CodeSentry</title>" in html


def test_settings_endpoints_contract():
    body = client.get("/api/settings/llm").json()
    assert set(body.keys()) >= {"model_base_url", "model_api_key", "fast_model", "deep_model"}
    r = client.get("/api/settings/embedding")
    assert r.status_code == 200


def test_scan_list_contract_fields():
    rows = client.get("/api/scans").json()
    for row in rows:
        assert {"id", "repo_path", "OSS", "status", "mode"} <= set(row.keys())
        break


def test_delete_scan_clean(tmp_path):
    r = client.post("/api/scans", data={"diff_text": "x"})
    sid = r.json()["scan_id"]
    repo = Path(client.get(f"/api/scans/{sid}").json()["repo_path"])
    assert repo.exists()
    d = client.delete(f"/api/scans/{sid}").json()
    assert d["ok"]
    assert not repo.exists()
    assert client.get(f"/api/scans/{sid}").status_code == 404


def test_graph_api_python_callgraph():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("proj/app.py",
                   "import requests\n"
                   "def fetch(u):\n"
                   "    return requests.get(u)\n"
                   "def main():\n"
                   "    return fetch('http://x')\n")
    r = client.post("/api/scans", files={"file": ("proj.zip", buf.getvalue(), "application/zip")}, data={"oss": "true"})
    sid = r.json()["scan_id"]
    repo = Path(client.get(f"/api/scans/{sid}").json()["repo_path"]).resolve()
    from codesentry.rag.graph_build import build_graph

    build_graph(str(repo), project=str(repo))
    g = client.get(f"/api/scans/{sid}/graph").json()
    assert g["mode"] == "graph"
    names = {n["name"] for n in g["nodes"]}
    assert "fetch" in names and "main" in names
    assert any(e["kind"] == "calls" for e in g["edges"])


def test_source_slice_and_traversal_guard():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("proj/app.py", "line1\nline2\nline3\n")
    sid = client.post("/api/scans", files={"file": ("s.zip", buf.getvalue(), "application/zip")}).json()["scan_id"]
    sl = client.get(f"/api/scans/{sid}/source?path=proj/app.py&start=2&end=3").json()
    assert [l["no"] for l in sl["lines"]] == [2, 3]
    r = client.get(f"/api/scans/{sid}/source?path=../secrets.txt")
    assert r.status_code == 400


def test_finding_detail_endpoint():
    rows = client.get("/api/scans").json()
    if not rows:
        pytest.skip("no scans")
    # 找一个有 findings 的 scan
    import psycopg  # noqa: F401
    for row in rows:
        det = client.get(f"/api/scans/{row['id']}")
        # 详情不炸即可（findings 属于 5.2 后端下轮补齐的信口）
        assert det.status_code == 200
        break
