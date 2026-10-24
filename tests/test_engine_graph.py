from codesentry.engines.codeql_graph import normalize_sarif_uri, parse_codeql_flows
from codesentry.engines.joern_graph import parse_graph_lines
from codesentry.rag.graph_delta import apply_engine_graph
from codesentry.rag.path_build import _feasibility


def test_parse_joern_graph_lines():
    text = (
        "JOERN_NODE|method|A.java|10|a.b.C.m\n"
        "JOERN_EDGE|calls|A.java|10|foo|a.b.C.m\n"
        "JOERN_FLOW|A.java|20|A.java|5|param|exec\n"
        "noise"
    )
    methods, edges = parse_graph_lines(text)
    assert methods[0]["name"] == "a.b.C.m"
    assert edges[0]["kind"] == "calls"
    assert edges[1]["kind"] == "dataflow"
    assert edges[1]["source"] == "param"


def test_parse_codeql_flows_and_uri(tmp_path):
    assert normalize_sarif_uri("file:///repo/app.py", "/repo") == "app.py"
    doc = {
        "runs": [{"results": [{"codeFlows": [{"threadFlows": [{"locations": [
            {"location": {"physicalLocation": {"artifactLocation": {"uri": "app.py"},
                                               "region": {"startLine": 3}}}},
            {"location": {"physicalLocation": {"artifactLocation": {"uri": "app.py"},
                                               "region": {"startLine": 5}}}},
        ]}]}]}]}],
    }
    edges = parse_codeql_flows(doc, "/repo")
    assert len(edges) == 1
    assert edges[0]["src_line"] == 3 and edges[0]["dst_line"] == 5


def test_apply_engine_graph_idempotent(tmp_path):
    from codesentry.db.pool import get_conn
    from codesentry.rag.graph_build import build_graph

    (tmp_path / "app.py").write_text(
        "def src(x):\n    return exec(x)\n\ndef sink(y):\n    return src(y)\n",
        encoding="utf-8",
    )
    project = str(tmp_path.resolve())
    built = build_graph(project, project=project)
    src = "function:app.py#src"
    dst = "function:app.py#sink"
    edges = [{"src": src, "dst": dst, "kind": "dataflow",
              "provenance": "joern", "confidence": 0.7}]
    first = apply_engine_graph(project, built["build_id"], [], edges)
    second = apply_engine_graph(project, built["build_id"], [], edges)
    assert first["dataflow"] == 1
    assert second["dataflow"] == 1
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM graph_edges WHERE project=%s"
                    " AND kind='dataflow'", (project,))
        assert int(cur.fetchone()[0]) == 1
        cur.execute("DELETE FROM graph_edges WHERE project=%s", (project,))
        cur.execute("DELETE FROM graph_nodes WHERE project=%s", (project,))
        cur.execute("DELETE FROM graph_files WHERE project=%s", (project,))
        cur.execute("DELETE FROM graph_builds WHERE project=%s", (project,))
        conn.commit()


def test_dataflow_edge_makes_path_proven():
    assert _feasibility([], [{"kind": "dataflow"}]) == "proven"
