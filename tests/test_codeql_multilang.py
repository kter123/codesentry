import json

from codesentry.agents.scan import run_scan_agent
from codesentry.engines.codeql import _parse_sarif
from codesentry.engines.codeql_graph import normalize_sarif_uri
from codesentry.models import EngineResult
from codesentry.scan_orchestrator import codeql_langs


def test_normalize_sarif_uri_variants(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "A B.java").write_text("class A {}", encoding="utf-8")
    assert normalize_sarif_uri("src/A%20B.java", str(repo)) == "src/A B.java"
    assert normalize_sarif_uri(str(repo / "src" / "A B.java"), str(repo)) == "src/A B.java"
    assert normalize_sarif_uri((repo / "src" / "A B.java").as_uri(), str(repo)) == "src/A B.java"
    assert normalize_sarif_uri("/etc/passwd", str(repo)) == ""


def test_parse_sarif_normalizes_uri(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "Cmd.java").write_text("class Cmd {}", encoding="utf-8")
    sarif = {
        "runs": [{
            "tool": {"driver": {"rules": [{"id": "java/command-line-injection",
                                           "properties": {"tags": ["security",
                                                                   "external/cwe/cwe-078"]}}]}},
            "results": [{
                "ruleIndex": 0, "level": "error",
                "message": {"text": "cmd"},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": (repo / "src" / "Cmd.java").as_uri()},
                    "region": {"startLine": 8},
                }}],
            }],
        }],
    }
    path = tmp_path / "r.sarif"
    path.write_text(json.dumps(sarif), encoding="utf-8")
    findings = _parse_sarif(path, str(repo))
    assert findings[0].file == "src/Cmd.java"
    assert findings[0].cwe == 78


def test_codeql_langs_dedupes_typescript():
    assert codeql_langs(["java", "python", "typescript", "javascript", "php"]) == [
        "java", "python", "javascript"
    ]


def test_codeql_graph_links_same_function_flow_to_sink(tmp_path):
    from codesentry.db.pool import get_conn
    from codesentry.engines.codeql_graph import run_codeql_graph
    from codesentry.rag.graph_build import build_graph
    from codesentry.rag.graph_delta import apply_engine_hints

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "A.java").write_text(
        "class A {\n"
        "  void f(String x) {\n"
        "    Runtime.getRuntime().exec(x);\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    built = build_graph(str(repo), project=str(repo.resolve()))
    apply_engine_hints(str(repo), built["build_id"], [{
        "file": "A.java", "line": 3, "rule_id": "java/command-line-injection",
        "cwe": 78, "severity": "high", "engine": "codeql", "message": "cmd",
    }])
    sarif = {
        "runs": [{
            "tool": {"driver": {"rules": [{"id": "java/command-line-injection"}]}},
            "results": [{
                "ruleIndex": 0, "level": "error",
                "message": {"text": "cmd"},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": "A.java"},
                    "region": {"startLine": 3},
                }}],
                "codeFlows": [{"threadFlows": [{"locations": [
                    {"location": {"physicalLocation": {
                        "artifactLocation": {"uri": "A.java"},
                        "region": {"startLine": 2},
                    }}},
                    {"location": {"physicalLocation": {
                        "artifactLocation": {"uri": "A.java"},
                        "region": {"startLine": 3},
                    }}},
                ]}]}],
            }],
        }],
    }
    path = tmp_path / "r.sarif"
    path.write_text(json.dumps(sarif), encoding="utf-8")
    try:
        stats = run_codeql_graph(str(path), str(repo), str(repo.resolve()),
                                 build_id=built["build_id"])
        assert stats["dataflow"] >= 1
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT src_key, dst_key FROM graph_edges WHERE project=%s"
                " AND kind='dataflow' AND provenance='codeql'",
                (str(repo.resolve()),),
            )
            rows = cur.fetchall()
        assert rows
        assert rows[0][0].startswith(("function:", "method:"))
        assert rows[0][1].startswith("sink:")
    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM graph_nodes WHERE project=%s", (str(repo.resolve()),))
            cur.execute("DELETE FROM graph_edges WHERE project=%s", (str(repo.resolve()),))
            cur.execute("DELETE FROM graph_builds WHERE project=%s", (str(repo.resolve()),))
            cur.execute("DELETE FROM graph_files WHERE project=%s", (str(repo.resolve()),))
            conn.commit()


def test_scan_agent_runs_codeql_per_language(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "A.java").write_text("class A {}", encoding="utf-8")
    (repo / "a.py").write_text("x = 1", encoding="utf-8")
    (repo / "a.ts").write_text("const x = 1", encoding="utf-8")
    called: list[str] = []

    def fake_codeql(**kwargs):
        called.append(kwargs["lang"])
        return EngineResult(engine="codeql", status="unavailable", reason="test")

    def fake_semgrep(**kwargs):
        return EngineResult(engine="semgrep", status="unavailable", reason="test")

    def fake_parallel(specs, **kwargs):
        return [spec() for spec in specs]

    monkeypatch.setattr("codesentry.agents.scan.run_codeql", fake_codeql)
    monkeypatch.setattr("codesentry.agents.scan.run_semgrep", fake_semgrep)
    monkeypatch.setattr("codesentry.agents.scan.run_engines_parallel", fake_parallel)
    monkeypatch.setattr(
        "codesentry.agents.scan.select_engines",
        lambda OSS, lang=None: ["codeql", "semgrep"],
    )
    state = {
        "repo_path": str(repo),
        "license_declaration": {"OSS": True},
        "profile": {"languages": ["java", "python", "typescript"]},
        "graph_build_id": 0,
    }
    update = run_scan_agent(state)
    assert sorted(called) == ["java", "javascript", "python"]
    assert update["phase"] in ("audit", "report")
