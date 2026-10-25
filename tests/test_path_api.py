import json
import uuid

from fastapi.testclient import TestClient

from codesentry.db.pool import get_conn
from codesentry.web.server import app

client = TestClient(app)


def _seed(tmp_path):
    sid = 985000 + (uuid.uuid4().int % 1000)
    repo = tmp_path / "work" / f"repo-{sid}"
    repo.mkdir(parents=True)
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
            (project, json.dumps({"method": "GET", "route": "/run"})),
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
            " sink_key, nodes, edges, length, score, feasibility, status, evidence)"
            " VALUES (%s,%s,0,'entry_to_sink','endpoint:GET:/run','','sink:app.py#eval:5',"
            " '[\"endpoint:GET:/run\",\"sink:app.py#eval:5\"]'::jsonb,"
            " '[{\"from\":\"endpoint:GET:/run\",\"to\":\"sink:app.py#eval:5\","
            "\"kind\":\"dataflow\"}]'::jsonb,2,0.9,'proven','finding','{\"reason\":\"x\"}'::jsonb)"
            " RETURNING id",
            (sid, "b" * 64),
        )
        pid = int(cur.fetchone()[0])
        conn.commit()
    return sid, pid, project, repo


def _cleanup(sid, project):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM audit_paths WHERE scan_id=%s", (sid,))
        cur.execute("DELETE FROM graph_nodes WHERE project=%s", (project,))
        cur.execute("DELETE FROM scans WHERE id=%s", (sid,))
        conn.commit()


def test_path_detail_resolves_nodes_and_edges(tmp_path, monkeypatch):
    sid, pid, project, _repo = _seed(tmp_path)
    monkeypatch.setenv("CODESENTRY_WORK_DIR", str(tmp_path / "work"))
    try:
        body = client.get(f"/api/scans/{sid}/paths/{pid}").json()
        assert body["id"] == pid
        assert len(body["nodes_detail"]) == 2
        assert body["nodes_detail"][0]["kind"] == "endpoint"
        assert body["edges_detail"][0]["src_kind"] == "endpoint"
        assert body["edges_detail"][0]["dst_kind"] == "sink"
    finally:
        _cleanup(sid, project)


def test_graph_focus_includes_path_nodes(tmp_path, monkeypatch):
    sid, _pid, project, _repo = _seed(tmp_path)
    monkeypatch.setenv("CODESENTRY_WORK_DIR", str(tmp_path / "work"))
    try:
        body = client.get(
            f"/api/scans/{sid}/graph",
            params={"limit": 100, "focus": "sink:app.py#eval:5"},
        ).json()
        keys = {n["key"] for n in body["nodes"]}
        assert "sink:app.py#eval:5" in keys
    finally:
        _cleanup(sid, project)
