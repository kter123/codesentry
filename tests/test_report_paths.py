import uuid

from codesentry.agents.report import run_report
from codesentry.db.pool import get_conn


def test_report_contains_path_section(tmp_path):
    sid = 986000 + (uuid.uuid4().int % 1000)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scans (id, repo_path, license_oss, license_declared_at)"
            " VALUES (%s,%s,true,now())",
            (sid, str(tmp_path)),
        )
        cur.execute(
            "INSERT INTO audit_paths (scan_id, path_key, round, kind, entry_key, source_key,"
            " sink_key, nodes, edges, length, score, feasibility, status)"
            " VALUES (%s,%s,0,'entry_to_sink','endpoint:GET:/run','','sink:app.py#eval:6',"
            " '[\"endpoint:GET:/run\",\"sink:app.py#eval:6\"]'::jsonb,"
            " '[{\"from\":\"endpoint:GET:/run\",\"to\":\"sink:app.py#eval:6\","
            "\"kind\":\"dataflow\"}]'::jsonb,2,0.9,'proven','finding')",
            (sid, "c" * 64),
        )
        conn.commit()
    try:
        out = tmp_path / "report"
        run_report({"scan_id": sid, "triaged_findings": [], "profile": {}}, str(out))
        text = (out / "report.md").read_text(encoding="utf-8")
        assert "## 攻击路径" in text
        assert "flowchart LR" in text
        assert "GET:/run" in text
        assert "dataflow" in text
    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM audit_paths WHERE scan_id=%s", (sid,))
            cur.execute("DELETE FROM scans WHERE id=%s", (sid,))
            conn.commit()


def test_report_without_paths_says_no_data(tmp_path):
    out = tmp_path / "report"
    run_report({"scan_id": 0, "triaged_findings": [], "profile": {}}, str(out))
    text = (out / "report.md").read_text(encoding="utf-8")
    assert "无路径数据" in text
