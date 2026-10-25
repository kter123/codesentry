from codesentry.db.pool import get_conn
from codesentry.rag.extractors.generic import extractor_for
from codesentry.rag.graph_build import build_graph
from codesentry.rag.graph_delta import apply_engine_graph
from codesentry.rag.path_build import build_paths


def test_js_anonymous_arrow_gets_function_and_route_edge(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.js").write_text(
        'const express = require("express");\n'
        'const { exec } = require("child_process");\n'
        "const app = express();\n"
        "\n"
        'app.get("/run", (req, res) => {\n'
        '  const cmd = req.query.cmd;\n'
        "  exec(cmd, (err, out) => res.send(out));\n"
        "});\n",
        encoding="utf-8",
    )
    parsed = extractor_for("javascript").extract("app.js",
                                                 (repo / "app.js").read_text())
    keys = {n.key for n in parsed.nodes}
    assert any("anon@L5" in key for key in keys), keys
    anon = next(n for n in parsed.nodes if "anon@L5" in n.key)
    assert any(e.src_key == "route:app.js#GET:/run" and e.dst_key == anon.key
               and e.kind == "routes_to" for e in parsed.edges)
    built = build_graph(str(repo), project=str(repo.resolve()))
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT node_key FROM graph_nodes WHERE project=%s AND kind='sink' LIMIT 1",
                    (str(repo.resolve()),))
        sink = cur.fetchone()[0]
    # 模拟 CodeQL 的 function→sink dataflow
    apply_engine_graph(str(repo.resolve()), built["build_id"], [], [{
        "src": anon.key, "dst": sink, "kind": "dataflow",
        "provenance": "test", "confidence": 0.9,
    }])
    build_paths(990100, str(repo.resolve()), built["build_id"],
                [{"file": "app.js", "line": 7, "rule_id": "js/command-line-injection",
                  "cwe": 78, "severity": "high", "message": "exec"}],
                min_score=0.2)
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT feasibility FROM audit_paths WHERE scan_id=990100"
                " ORDER BY score DESC LIMIT 1"
            )
            row = cur.fetchone()
        assert row and row[0] in ("proven", "likely")
    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM audit_paths WHERE scan_id=990100")
            cur.execute("DELETE FROM graph_nodes WHERE project=%s", (str(repo.resolve()),))
            cur.execute("DELETE FROM graph_edges WHERE project=%s", (str(repo.resolve()),))
            cur.execute("DELETE FROM graph_builds WHERE project=%s", (str(repo.resolve()),))
            cur.execute("DELETE FROM graph_files WHERE project=%s", (str(repo.resolve()),))
            conn.commit()
