import json
import uuid

from codesentry.agents.retrieval import run_retrieval
from codesentry.agents.state import new_state
from codesentry.db.pool import get_conn
from codesentry.rag import experience
from codesentry.rag.graphrag import build_code_graph, neighbors


def _cleanup(project: str, cwe: int) -> None:
    with get_conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM code_graph_edges WHERE project=%s", (project,))
        cur.execute("DELETE FROM code_graph_nodes WHERE project=%s", (project,))
        cur.execute("DELETE FROM code_chunks WHERE project=%s", (project,))
        cur.execute("DELETE FROM vuln_cases WHERE cwe=%s AND source LIKE %s", (cwe, "unit:%"))
        cur.execute("DELETE FROM audit_patterns WHERE name LIKE %s", ("unit-%",))
        c.commit()


def test_experience_add_search_and_promote():
    cwe = 918
    _cleanup("/tmp/rag-unit", cwe)
    try:
        assert experience.add_pattern(
            name="unit-ssrf", lang="python", cwe=cwe,
            pattern="requests.get(user_url)", guidance="校验 URL，阻断私网",
        )
        rows = experience.search_patterns("requests.get", cwe=cwe, limit=5)
        assert any(r["name"] == "unit-ssrf" for r in rows)

        assert experience.add_vuln_case(
            title="unit ssrf case", cwe=cwe, lang="python", pattern="requests.get(url)",
            exploit_chain=["source", "sink"], poc="print(1)", fix="allowlist", source="unit:1",
        )
        cases = experience.search_vuln_cases("requests.get", cwe=cwe, limit=5)
        assert any(c["title"] == "unit ssrf case" for c in cases)

        with get_conn() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO scans (repo_path, license_oss, license_declared_at) VALUES ('/tmp/rag-unit',false,now()) RETURNING id"
            )
            sid = int(cur.fetchone()[0])
            cur.execute(
                "INSERT INTO findings (scan_id, rule_id, cwe, severity, confidence, file, line, message, engine, verdict)"
                " VALUES (%s,'unit.rag',%s,'HIGH',0.9,'/tmp/a.py',1,'unit promote','semgrep','verified')",
                (sid, cwe),
            )
            c.commit()
        assert experience.promote_findings(sid) >= 1
        with get_conn() as c, c.cursor() as cur:
            cur.execute("SELECT count(*) FROM vuln_cases WHERE source=%s", (f"scan:{sid}:unit.rag:/tmp/a.py:1",))
            assert int(cur.fetchone()[0]) == 1
    finally:
        with get_conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM findings WHERE message='unit promote'")
            cur.execute("DELETE FROM scans WHERE repo_path='/tmp/rag-unit'")
            cur.execute("DELETE FROM vuln_cases WHERE source LIKE %s", ("scan:%:unit.rag:%",))
            c.commit()
        _cleanup("/tmp/rag-unit", cwe)


def test_code_graph_build_and_neighbors():
    project = f"/tmp/rag-graph-{uuid.uuid4().hex[:6]}"
    try:
        with get_conn() as c, c.cursor() as cur:
            for name, refs, start, end in (("a", ["b"], 1, 5), ("b", [], 6, 10)):
                cur.execute(
                    "INSERT INTO code_chunks (project, path, symbol_name, symbol_kind, start_line,"
                    " end_line, signature, call_refs, content, lang, content_sha256)"
                    " VALUES (%s,%s,%s,'function',%s,%s,%s,%s,%s,'python',%s)",
                    (project, f"{project}/x.py", name, start, end, f"def {name}()", json.dumps(refs),
                     f"def {name}(): pass", f"{project}-{name}"),
                )
            c.commit()
        assert build_code_graph(project) >= 2
        out = neighbors(project, f"{project}/x.py:a")
        keys = {n["key"] for n in out["nodes"]}
        assert f"{project}/x.py:b" in keys
    finally:
        _cleanup(project, 0)


def test_retrieval_includes_experience_fields():
    s = new_state("/tmp/rag-nonexistent", OSS=False)
    s["engine_findings"] = [{"rule_id": "unit.rag2", "cwe": 918, "line": 1,
                             "message": "requests.get(user_url)", "file": "/tmp/x.py"}]
    out = run_retrieval(s)
    ev = out["evidence"]["unit.rag2@1"]
    assert "vuln_cases" in ev and "patterns" in ev and "graph" in ev
