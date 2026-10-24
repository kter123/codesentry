import uuid

from fastapi.testclient import TestClient

from codesentry.db.pool import get_conn
from codesentry.web.server import app

client = TestClient(app)


def _profile_name() -> str:
    return f"unit-api-{uuid.uuid4().hex[:8]}"


def _cleanup_profile(pid: int) -> None:
    with get_conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM llm_profiles WHERE id=%s", (pid,))
        c.commit()


def test_profiles_crud_mask_and_delete():
    from codesentry.control import profiles as profile_svc

    prev_default = profile_svc.get_default()
    name = _profile_name()
    r = client.post("/api/llm-profiles", json={
        "name": name, "base_url": "https://example.test/v1",
        "fast_model": "f", "deep_model": "d", "api_key": "sk-secret-123456789",
        "protocol": "openai-compatible",
    })
    assert r.status_code == 200, r.text
    p = r.json()
    pid = p["id"]
    try:
        assert p["api_key"].endswith("…") and "sk-secret" not in str(p)
        lst = client.get("/api/llm-profiles").json()["profiles"]
        assert any(x["id"] == pid for x in lst)
        up = client.put(f"/api/llm-profiles/{pid}", json={"temperature": 0.3})
        assert up.status_code == 200 and up.json()["temperature"] == 0.3
        assert client.post(f"/api/llm-profiles/{pid}/default").status_code == 200
        assert client.delete(f"/api/llm-profiles/{pid}").json()["ok"] is True
    finally:
        _cleanup_profile(pid)
        if prev_default is not None:
            profile_svc.set_default(prev_default.id, actor="test")


def test_profile_test_and_probe(monkeypatch):
    name = _profile_name()
    r = client.post("/api/llm-profiles", json={
        "name": name, "base_url": "https://example.test/v1", "fast_model": "f", "deep_model": "d",
    })
    pid = r.json()["id"]
    try:
        monkeypatch.setattr("codesentry.agents.llm.LLMClient.complete", lambda self, *a, **k: "OK")
        t = client.post(f"/api/llm-profiles/{pid}/test").json()
        assert t["ok"] is True
        monkeypatch.setattr("codesentry.control.profiles.probe_models",
                            lambda pid, limit=5: {"ok": True, "models": ["m"]})
        assert client.post(f"/api/llm-profiles/{pid}/probe").json()["models"] == ["m"]
    finally:
        _cleanup_profile(pid)


def test_presets_include_opencode_go():
    presets = client.get("/api/llm-profiles/presets").json()["presets"]
    assert presets["opencode-go"]["base_url"] == "https://opencode.ai/zen/go/v1"
    assert presets["opencode-go"]["extra_headers"]["x-opencode-session"] == "${session_id}"


def test_agents_detail_update_dry_run_and_preview():
    before = client.get("/api/agents/triage").json()["config"]
    try:
        r = client.put("/api/agents/triage", json={"timeout_s": 321})
        assert r.status_code == 200 and r.json()["agent"]["timeout_s"] == 321
        detail = client.get("/api/agents/triage").json()
        assert "config" in detail and "prompt" in detail
        dry = client.post("/api/agents/triage/dry-run", json={"state": {"engine_findings": []}}).json()
        assert dry["agent"] == "triage" and "system_prompt" in dry
        prev = client.post("/api/agents/triage/preview-prompt").json()
        assert prev["agent"] == "triage" and "prompt_tokens_est" in prev
        assert client.get("/api/agents/triage/prompt").status_code == 200
        assert client.get("/api/agents/triage/skills").status_code == 200
        stats = client.get("/api/agents/triage/stats?days=1").json()
        assert stats["agent"] == "triage"
    finally:
        client.put("/api/agents/triage", json={"timeout_s": before["timeout_s"]})


def test_usage_quota_and_audit():
    assert client.get("/api/usage/summary?group_by=agent").status_code == 200
    q = client.get("/api/usage/quota").json()
    assert "tokens_used" in q and "usd_used" in q
    assert client.get("/api/audit?limit=5").status_code == 200


def test_prompt_activate_diff_lint():
    name = f"unit-prompt-{uuid.uuid4().hex[:8]}"
    try:
        v1 = client.post("/api/prompts", json={"name": name, "body": "line a"}).json()["version"]
        v2 = client.post("/api/prompts", json={"name": name, "body": "line b"}).json()["version"]
        assert client.post(f"/api/prompts/{name}/activate", json={"version": v1}).json()["ok"]
        d = client.get(f"/api/prompts/{name}/diff?a={v1}&b={v2}").json()["diff"]
        assert "-line a" in d and "+line b" in d
        lint = client.post("/api/prompts/lint", json={"body": "输出 JSON"}).json()
        assert lint["ok"] is True
        assert client.post("/api/prompts/lint", json={"body": "rm -rf /"}).json()["ok"] is False
    finally:
        with get_conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM prompt_versions WHERE agent=%s", (name,))
            c.commit()


def test_skill_preview_and_usage():
    name = f"unit-skill-{uuid.uuid4().hex[:8]}"
    md = f"---\nname: {name}\ndescription: d\n---\n\n按 source->sink 核验。"
    try:
        assert client.post("/api/skills/upload", json={"name": "x", "body": md}).status_code == 200
        assert client.post(f"/api/skills/{name}/assign", json={"agent": "triage"}).status_code == 200
        prev = client.post(f"/api/skills/{name}/preview", json={"agents": ["triage"]}).json()
        assert name in prev["agents"]["triage"]["skills_block"]
        assert client.get(f"/api/skills/{name}/usage").status_code == 200
    finally:
        with get_conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM skill_assignments WHERE skill_name=%s", (name,))
            cur.execute("DELETE FROM skill_versions WHERE name=%s", (name,))
            cur.execute("DELETE FROM skills WHERE name=%s", (name,))
            c.commit()


def test_unknown_agent_returns_404():
    for path in ("/api/agents/nope", "/api/agents/nope/prompt", "/api/agents/nope/skills"):
        assert client.get(path).status_code == 404, path
    assert client.post("/api/agents/nope/dry-run", json={}).status_code == 404
    assert client.put("/api/agents/nope", json={"enabled": True}).status_code == 404


def test_artifacts_and_calibration_endpoints():
    assert client.get("/api/scans/999999/artifacts").json()["artifacts"] == []
    assert client.get("/api/scans/999999/artifacts/verify").json()["ok"] is True
    assert client.get("/api/calibration").status_code == 200
    r = client.post("/api/calibration/fit",
                    json={"pairs": [{"raw": 0.9, "label": 1}, {"raw": 0.1, "label": 0}]})
    assert r.status_code == 200 and "ece" in r.json()


def test_graph_templates_and_prompt_evals():
    name = f"unit-tpl-{uuid.uuid4().hex[:8]}"
    cfg = {
        "nodes": [{"id": n} for n in (
            "recon", "graph_build", "scan", "audit", "triage", "deploy", "poc_gen", "report"
        )],
        "edges": [{"from": "recon", "to": "graph_build"},
                  {"from": "graph_build", "to": "scan"}, {"from": "scan", "to": "audit"},
                  {"from": "audit", "to": "triage"}, {"from": "triage", "to": "deploy"},
                  {"from": "deploy", "to": "poc_gen"}, {"from": "poc_gen", "to": "report"}],
        "settings": {},
    }
    try:
        assert client.post("/api/graph-templates/validate",
                           json={"name": name, "config": cfg}).json()["ok"] is True
        bad = {"nodes": [{"id": "recon"}, {"id": "scan"}], "edges": []}
        assert client.post("/api/graph-templates/validate",
                           json={"name": name, "config": bad}).json()["ok"] is False
        r = client.post("/api/graph-templates", json={"name": name, "config": cfg})
        assert r.status_code == 200, r.text
        assert client.get("/api/graph-templates").status_code == 200
        assert client.post("/api/prompts/eval", json={
            "agent": "triage", "version": 1, "dataset": "unit",
            "metrics": {"recall": 0.9, "precision": 0.8, "fp_rate": 0.1, "ece": 0.05, "n": 10},
        }).status_code == 200
        assert client.get("/api/prompt-evals?agent=triage").status_code == 200
    finally:
        with get_conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM graph_templates WHERE name=%s", (name,))
            cur.execute("DELETE FROM prompt_evals WHERE dataset='unit'")
            c.commit()


def test_prompt_eval_run(monkeypatch):
    monkeypatch.setattr(
        "codesentry.agents.llm.LLMClient.for_agent",
        classmethod(lambda cls, *a, **k: object()),
    )
    monkeypatch.setattr(
        "codesentry.agents.triage.triage_one",
        lambda *a, **k: {"verdict": "keep", "confidence": 0.9, "rationale": "r", "fix_advice": ""},
    )
    r = client.post("/api/prompts/eval/run",
                    json={"agent": "triage", "dataset": "selfbuilt", "limit": 2})
    assert r.status_code == 200, r.text
    m = r.json()["metrics"]
    assert m["n"] == 2 and "recall" in m and "ece" in m


def test_assist_ask(monkeypatch):
    class FakeLLM:
        def complete(self, system, user, model_role="deep"):
            return "根据证据，该 finding 可达。"

    monkeypatch.setattr(
        "codesentry.agents.llm.LLMClient.for_agent",
        classmethod(lambda cls, *a, **k: FakeLLM()),
    )
    r = client.post("/api/assist/ask", json={"question": "这个 SSRF 可信吗？", "scan_id": 999999})
    assert r.status_code == 200, r.text
    assert "可达" in r.json()["answer"]
    assert isinstance(r.json()["sources"], list)


def test_kb_ops_and_comments():
    src = f"unit-kb-{uuid.uuid4().hex[:6]}"
    assert client.get("/api/kb/stats").status_code == 200
    assert client.post("/api/kb/import", json={
        "source": src, "title": "t", "content": "第一段关于 SSRF。\n\n第二段关于 SQL 注入。",
    }).status_code == 200
    rows = client.post("/api/kb/search", json={"query": "SSRF"}).json()["rows"]
    assert isinstance(rows, list)
    prev = client.post("/api/kb/preview", json={"content": "第一段\n\n第二段", "size": 10}).json()
    assert prev["count"] >= 1
    assert client.get("/api/kb/chunks", params={"source": src}).status_code == 200
    r = client.post("/api/scans", data={"diff_text": "x"})
    sid = r.json()["scan_id"]
    try:
        c = client.post(f"/api/scans/{sid}/comments", json={"body": "复核备注", "author": "unit"})
        assert c.status_code == 200
        assert client.get(f"/api/scans/{sid}/comments").json()["comments"]
    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM review_comments WHERE scan_id=%s", (sid,))
            cur.execute("DELETE FROM findings WHERE scan_id=%s", (sid,))
            cur.execute("DELETE FROM node_runs WHERE scan_id=%s", (sid,))
            cur.execute("DELETE FROM budget_ledger WHERE scan_id=%s", (sid,))
            cur.execute("DELETE FROM scans WHERE id=%s", (sid,))
            cur.execute("DELETE FROM kb_chunks WHERE source=%s", (src,))
            conn.commit()


def test_retention_and_disk():
    assert client.get("/api/ops/disk").status_code == 200
    with get_conn() as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO scans (repo_path, license_oss, license_declared_at, created_at)"
            " VALUES ('/tmp/retention-unit',false,now(), now() - interval '3 days') RETURNING id"
        )
        sid = int(cur.fetchone()[0]); c.commit()
    r = client.post("/api/ops/retention", json={"days": 1})
    assert r.status_code == 200 and r.json()["deleted"] >= 1
    with get_conn() as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM scans WHERE id=%s", (sid,))
        assert int(cur.fetchone()[0]) == 0


def test_assist_copilot(monkeypatch):
    class FakeLLM:
        def complete(self, system, user, model_role="deep"):
            return "建议：补充不可信内容分隔符；明确 JSON 契约。"

    monkeypatch.setattr(
        "codesentry.agents.llm.LLMClient.for_agent",
        classmethod(lambda cls, *a, **k: FakeLLM()),
    )
    r = client.post("/api/assist/copilot", json={"agent": "triage"})
    assert r.status_code == 200, r.text
    assert "建议" in r.json()["suggestion"]


def test_health():
    h = client.get("/api/health").json()
    assert "db" in h and "engines" in h and "queue" in h
    assert h["db"]["ok"] is True
