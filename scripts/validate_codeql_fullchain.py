"""CodeQL 全链路验证：fixture → 扫描 → CodeQL → 图 → 路径 → Triage → 报告。

用法：
    PYTHONPATH=src uv run python scripts/validate_codeql_fullchain.py --lang java
    ... --lang python --lang javascript
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = {
    "java": ("CmdServlet.java", "java"),
    "python": ("py_cmd.py", "python"),
    "javascript": ("js_cmd.js", "javascript"),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", choices=sorted(FIXTURES), default="java")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    os.environ.setdefault("CODESENTRY_LLM_ENABLED", "false")
    os.environ.setdefault("CODESENTRY_DEPLOY_ENABLED", "false")
    os.environ.setdefault("CODESENTRY_POC_RUN", "off")
    os.environ.setdefault("CODESENTRY_SCHEDULER_ENABLED", "false")

    from dotenv import load_dotenv

    load_dotenv()

    fixture, _ = FIXTURES[args.lang]
    tmp = Path(tempfile.mkdtemp(prefix=f"cs-codeql-{args.lang}-"))
    repo = tmp / "repo"
    repo.mkdir()
    shutil.copy2(ROOT / "tests" / "fixtures" / "codeql" / fixture, repo / fixture)

    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.db.pool import get_conn
    from codesentry.orchestrator.runner import run_scan_graph
    from codesentry.web.server import _insert_scan

    ensure_control_schema()
    scan_id = _insert_scan(str(repo), True)
    out = str(tmp / "report")
    code = run_scan_graph(str(repo), True, out, scan_id=scan_id)
    project = str(repo.resolve())

    findings = []
    edges = []
    paths = []
    artifacts = []
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, rule_id, cwe, severity, engine, file, line, confidence, path_id"
            " FROM findings WHERE scan_id=%s ORDER BY id", (scan_id,)
        )
        cols = ["id", "rule_id", "cwe", "severity", "engine", "file", "line",
                "confidence", "path_id"]
        findings = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.execute(
            "SELECT src_key, dst_key, kind, provenance FROM graph_edges"
            " WHERE project=%s AND (provenance='codeql' OR kind='dataflow') LIMIT 20",
            (project,),
        )
        edges = [{"src": r[0], "dst": r[1], "kind": r[2], "provenance": r[3]}
                 for r in cur.fetchall()]
        cur.execute(
            "SELECT id, entry_key, sink_key, feasibility, status, score"
            " FROM audit_paths WHERE scan_id=%s ORDER BY score DESC LIMIT 10", (scan_id,)
        )
        paths = [{"id": r[0], "entry": r[1], "sink": r[2], "feasibility": r[3],
                  "status": r[4], "score": r[5]} for r in cur.fetchall()]
        cur.execute(
            "SELECT node, output_preview FROM agent_artifacts WHERE scan_id=%s"
            " AND node='scan' ORDER BY seq DESC LIMIT 1", (scan_id,)
        )
        row = cur.fetchone()
        if row:
            try:
                artifacts = json.loads(row[1])
            except json.JSONDecodeError:
                artifacts = {"raw": str(row[1])[:500]}

    engine_graph = (artifacts.get("graph_delta") or {}).get("engine_graph") or {}
    codeql_stats = engine_graph.get("codeql") or {}
    report = Path(out) / "report.md"
    result = {
        "lang": args.lang,
        "scan_id": scan_id,
        "exit_code": code,
        "codeql": codeql_stats,
        "findings": findings,
        "graph_edges": edges,
        "proven_paths": sum(1 for p in paths if p["feasibility"] == "proven"),
        "paths": paths,
        "report_exists": report.is_file(),
        "report_has_codeql_text": "CodeQL" in report.read_text(encoding="utf-8")
        if report.is_file() else False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not args.keep:
        shutil.rmtree(tmp, ignore_errors=True)
    ok = code == 0 and result["report_exists"] and bool(codeql_stats)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
