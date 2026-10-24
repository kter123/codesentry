"""M5.3 管理面板 API 自动化测试（agents/prompts/skills/rules/review 契约）。"""

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("CODESENTRY_DATABASE_URL", "postgresql://codesentry:devtest@127.0.0.1:5432/codesentry")

from codesentry.web.server import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _work_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESENTRY_WORK_DIR", str(tmp_path / "work"))


def test_agents_list():
    r = client.get("/api/agents")
    assert r.status_code == 200
    names = [a["name"] for a in r.json()["agents"]]
    assert {"recon", "scan", "audit", "triage", "deploy", "poc_gen", "report"} <= set(names)


def test_agent_timeline():
    r = client.post("/api/scans", data={"diff_text": "x"})
    sid = r.json()["scan_id"]
    r2 = client.get(f"/api/scans/{sid}/agents/timeline")
    assert r2.status_code == 200 and isinstance(r2.json()["nodes"], list)


def test_prompts_create_versions_rollback():
    r1 = client.post("/api/prompts", json={"name": "triage-sys", "body": "v1 body"}).json()
    r2 = client.post("/api/prompts", json={"name": "triage-sys", "body": "v2 body"}).json()
    assert r2["version"] == r1["version"] + 1
    vs = client.get("/api/prompts/triage-sys/versions").json()["versions"]
    assert vs[0]["version"] == r2["version"]
    rb = client.post("/api/prompts/triage-sys/rollback", json={"version": r1["version"]}).json()
    assert rb["new_version"] == r2["version"] + 1


def test_skill_upload_and_assign():
    md = "---\nname: taint-chain-audit\ndescription: 污点链审计要点\n---\n\n按 source->sink 逐跳核验。@ref:guide"
    r = client.post("/api/skills/upload", json={"name": "tmp", "body": md})
    assert r.status_code == 200, r.text
    name = r.json()["name"]
    a = client.post(f"/api/skills/{name}/assign", json={"agent": "triage", "enabled": True})
    assert a.json()["ok"]
    lst = client.get("/api/skills").json()["skills"]
    assert any(s["name"] == name and s["assigned"].get("triage") for s in lst)


def test_skill_rejects_bad_frontmatter():
    r = client.post("/api/skills/upload", json={"name": "x", "body": "no frontmatter here"})
    assert r.status_code == 400


def test_rules_list_and_validate():
    r = client.get("/api/rules")
    assert r.status_code == 200 and len(r.json()["rules"]) >= 20
    v = client.post("/api/rules/validate", json={"yaml": "rules:\n  - id: t.y\n    message: m\n    severity: ERROR\n    languages: [python]\n    pattern: requests.get($U)"})
    assert v.json()["ok"]


def test_rules_reject_invalid_yaml():
    v = client.post("/api/rules/validate", json={"yaml": "rules: [broken"})
    assert not v.json()["ok"]


def test_rule_not_found_404():
    r = client.get("/api/rules/no.such.rule")
    assert r.status_code == 404
