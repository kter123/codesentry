import uuid

from codesentry.db.pool import get_conn
from codesentry.rag.extractors import extract
from codesentry.rag.graph_build import build_graph
from codesentry.rag.graph_query import entrypoints, neighbors, paths


def _write(tmp_path, rel: str, body: str):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_extractors_produce_nodes_and_routes():
    py = extract("app.py", "python", """
from flask import Flask, request
app = Flask(__name__)
def helper(x):
    return eval(x)
class Svc:
    def run(self, cmd):
        return helper(cmd)
@app.route("/user/<uid>", methods=["GET"])
def get_user(uid):
    return eval(request.args.get("q"))
""")
    assert any(n.kind == "class" for n in py.nodes)
    assert any(n.kind == "method" for n in py.nodes)
    assert any(e.kind == "routes_to" for e in py.edges)
    assert py.endpoints[0]["route"] == "/user/<uid>"

    java = extract("src/UserController.java", "java", """
package com.x;
import org.springframework.web.bind.annotation.*;
@RestController
@RequestMapping("/api")
public class UserController {
    @GetMapping("/user/{id}")
    @PreAuthorize("hasRole('ADMIN')")
    public String getUser(@PathVariable String id) {
        st.execute("select " + id);
        return id;
    }
}
""")
    ep = java.endpoints[0]
    assert ep["route"] == "/api/user/{id}"
    assert ep["permission"] == "管理员权限"
    method = next(n for n in java.nodes if n.kind == "method")
    assert method.attrs["sinks"]


def test_build_is_idempotent_and_incremental(tmp_path):
    project = f"unit-graph-{uuid.uuid4().hex[:8]}"
    _write(tmp_path, "app.py", "def helper(x):\n    return eval(x)\n\ndef main():\n    return helper(1)\n")
    _write(tmp_path, "Controller.java", """
package com.x;
import org.springframework.web.bind.annotation.*;
@RestController
public class Controller {
    @GetMapping("/ping")
    public String ping(@RequestParam String q) {
        return q;
    }
}
""")
    try:
        first = build_graph(str(tmp_path), project=project)
        assert first["ok"] is True
        assert first["stats"]["files_parsed"] == 2
        second = build_graph(str(tmp_path), project=project, mode="diff")
        assert second["stats"]["files_parsed"] == 0
        assert second["stats"]["nodes"] == first["stats"]["nodes"]
        assert second["stats"]["edges"] == first["stats"]["edges"]

        _write(tmp_path, "app.py", "def helper(x):\n    return eval(x)\n\ndef main():\n    return helper(2)\n\ndef extra():\n    return helper(3)\n")
        third = build_graph(str(tmp_path), project=project, mode="diff")
        assert third["stats"]["files_parsed"] == 1
        assert third["stats"]["nodes"] >= first["stats"]["nodes"]

        eps = entrypoints(project)
        assert any(e["route"] == "/ping" for e in eps)
        graph = neighbors(project, "function:app.py#main", depth=1)
        assert any(e["kind"] == "calls" for e in graph["edges"])
        assert paths(project, "function:app.py#main", "function:app.py#helper")
    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM graph_edges WHERE project=%s", (project,))
            cur.execute("DELETE FROM graph_nodes WHERE project=%s", (project,))
            cur.execute("DELETE FROM graph_endpoints WHERE project=%s", (project,))
            cur.execute("DELETE FROM graph_files WHERE project=%s", (project,))
            cur.execute("DELETE FROM graph_builds WHERE project=%s", (project,))
            conn.commit()
