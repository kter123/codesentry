import json
import uuid

from codesentry.agents.poc_gen import _path_context, gen_poc, run_poc_gen
from codesentry.db.pool import get_conn


class _FakeLLM:
    def __init__(self):
        self.user = ""

    def complete(self, system, user, model_role="deep"):
        self.user = user
        return '{"exploit_chain": ["entry", "sink"], "poc_script": "print(1)", "notes": ""}'


def _seed(tmp_path):
    sid = 980000 + (uuid.uuid4().int % 1000)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("x", encoding="utf-8")
    project = str(repo.resolve())
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scans (id, repo_path, license_oss, license_declared_at)"
            " VALUES (%s,%s,true,now())",
            (sid, str(repo)),
        )
        cur.execute(
            "INSERT INTO graph_nodes (project, node_key, kind, name, path, start_line,"
            " end_line, qualified_name, lang, attrs, build_id)"
            " VALUES (%s,'endpoint:GET:/run','endpoint','GET /run','app.py',1,5,'','python',"
            " %s::jsonb,1)",
            (project, json.dumps({"method": "GET", "route": "/run",
                                  "permission": "公开"})),
        )
        cur.execute(
            "INSERT INTO graph_nodes (project, node_key, kind, name, path, start_line,"
            " end_line, qualified_name, lang, attrs, build_id)"
            " VALUES (%s,'sink:app.py#eval:5','sink','eval','app.py',5,5,'','python',"
            " '{}'::jsonb,1)",
            (project,),
        )
        cur.execute(
            "INSERT INTO audit_paths (scan_id, path_key, round, kind, entry_key, source_key,"
            " sink_key, nodes, edges, length, score, feasibility, status)"
            " VALUES (%s,%s,0,'entry_to_sink','endpoint:GET:/run','','sink:app.py#eval:5',"
            " '[\"endpoint:GET:/run\",\"sink:app.py#eval:5\"]'::jsonb,"
            " '[{\"from\":\"endpoint:GET:/run\",\"to\":\"sink:app.py#eval:5\","
            "\"kind\":\"dataflow\"}]'::jsonb,2,0.9,'proven','pending') RETURNING id",
            (sid, "a" * 64),
        )
        pid = int(cur.fetchone()[0])
        conn.commit()
    return sid, pid, project


def _cleanup(sid: int, project: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM audit_paths WHERE scan_id=%s", (sid,))
        cur.execute("DELETE FROM graph_nodes WHERE project=%s", (project,))
        cur.execute("DELETE FROM graph_edges WHERE project=%s", (project,))
        cur.execute("DELETE FROM scans WHERE id=%s", (sid,))
        conn.commit()


def test_path_context_contains_entry_and_url(tmp_path):
    sid, pid, project = _seed(tmp_path)
    try:
        ctx = _path_context(sid, {"path_id": pid}, "http://127.0.0.1:8080/")
        assert ctx["path_id"] == pid
        assert ctx["entry"]["method"] == "GET"
        assert ctx["entry"]["route"] == "/run"
        assert ctx["entry"]["full_url"] == "http://127.0.0.1:8080/run"
        assert ctx["feasibility"] == "proven"
        assert any(n["key"] == "sink:app.py#eval:5" for n in ctx["nodes"])
    finally:
        _cleanup(sid, project)


def test_path_context_does_not_cross_scan(tmp_path):
    sid, pid, project = _seed(tmp_path)
    try:
        assert _path_context(sid + 1, {"path_id": pid}, "http://x") == {}
    finally:
        _cleanup(sid, project)


def test_path_context_without_target_does_not_invent_host(tmp_path):
    sid, pid, project = _seed(tmp_path)
    try:
        ctx = _path_context(sid, {"path_id": pid}, "")
        assert ctx["entry"]["route"] == "/run"
        assert ctx["entry"]["full_url"] == ""
        assert ctx["target_url"] == ""
    finally:
        _cleanup(sid, project)


def test_gen_poc_prompt_includes_path_context(tmp_path):
    sid, pid, project = _seed(tmp_path)
    try:
        ctx = _path_context(sid, {"path_id": pid}, "http://127.0.0.1:8080")
        llm = _FakeLLM()
        out = gen_poc(
            llm, {"cwe": 95, "rule_id": "path.95", "line": 5, "file": "app.py",
                  "message": "eval", "path_id": pid},
            {}, path_context=ctx,
        )
        assert out["path_id"] == pid
        assert out["entry_url"] == "http://127.0.0.1:8080/run"
        body = json.loads(llm.user)
        assert body["path_context"]["entry"]["route"] == "/run"
        assert body["path_context"]["path_id"] == pid
    finally:
        _cleanup(sid, project)


def test_run_poc_gen_attaches_path_context(tmp_path, monkeypatch):
    sid, pid, project = _seed(tmp_path)
    monkeypatch.setenv("CODESENTRY_POC_RUN", "off")
    monkeypatch.setenv("CODESENTRY_WORK_DIR", str(tmp_path / "work"))
    try:
        state = {
            "scan_id": sid,
            "target_url": "http://127.0.0.1:8080",
            "triaged_findings": [{
                "rule_id": "path.95", "cwe": 95, "severity": "high",
                "confidence": 0.8, "file": "app.py", "line": 5,
                "message": "eval", "engine": "agent", "path_id": pid,
            }],
            "evidence": {},
        }
        out = run_poc_gen(state, llm=_FakeLLM())
        poc = out["poc_results"]["path.95@5"]
        assert poc["path_id"] == pid
        assert poc["entry_url"] == "http://127.0.0.1:8080/run"
        assert poc["poc_file"]
    finally:
        _cleanup(sid, project)
