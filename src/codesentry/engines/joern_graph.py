"""Joern CPG → 图增量：调用边与参数→sink 数据流（可选，失败降级）。"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

_NODE = "JOERN_NODE|"
_CALL = "JOERN_EDGE|"
_FLOW = "JOERN_FLOW|"

_CALLS_SCRIPT = """
import _root_.io.shiftleft.semanticcpg.language.*
val cpg2 = loadCpg("%(cpg)s").get
cpg2.method.l.take(5000).foreach { m =>
  println("JOERN_NODE|method|" + m.file.name.headOption.getOrElse("") + "|" +
    m.lineNumber.headOption.getOrElse(-1) + "|" + m.fullName)
}
cpg2.call.l.take(20000).foreach { c =>
  println("JOERN_EDGE|calls|" + c.method.file.name.headOption.getOrElse("") + "|" +
    c.method.lineNumber.headOption.getOrElse(-1) + "|" + c.name + "|" +
    c.method.fullName.headOption.getOrElse(""))
}
cpg2.close
"""

_FLOW_SCRIPT = """
import _root_.io.joern.dataflowengineoss.language.*
import _root_.io.shiftleft.semanticcpg.language.*
val cpg2 = loadCpg("%(cpg)s").get
val names = List("exec", "readString", "readAllLines", "getInputStream", "eval",
  "system", "popen", "execute", "executeQuery", "newFile", "Command")
names.flatMap(n => cpg2.call.name(n).l).take(1000).foreach { s =>
  s.reachableBy(cpg2.parameter).l.take(20).foreach { p =>
    println("JOERN_FLOW|" + s.method.file.name.headOption.getOrElse("") + "|" +
      s.lineNumber.headOption.getOrElse(-1) + "|" +
      p.method.file.name.headOption.getOrElse("") + "|" +
      p.lineNumber.headOption.getOrElse(-1) + "|" +
      p.name + "|" + s.name)
  }
}
cpg2.close
"""


def parse_graph_lines(text: str) -> tuple[list[dict], list[dict]]:
    methods: list[dict] = []
    edges: list[dict] = []
    for line in text.splitlines():
        if line.startswith(_NODE):
            parts = line[len(_NODE):].split("|")
            if len(parts) >= 4:
                methods.append({"file": parts[1], "line": _int(parts[2]),
                                "name": "|".join(parts[3:])})
        elif line.startswith(_CALL):
            parts = line[len(_CALL):].split("|")
            if len(parts) >= 5:
                edges.append({"kind": "calls", "caller_file": parts[1],
                              "caller_line": _int(parts[2]), "callee": parts[3],
                              "callee_owner": "|".join(parts[4:])})
        elif line.startswith(_FLOW):
            parts = line[len(_FLOW):].split("|")
            if len(parts) >= 6:
                edges.append({"kind": "dataflow", "sink_file": parts[0],
                              "sink_line": _int(parts[1]), "source_file": parts[2],
                              "source_line": _int(parts[3]), "source": parts[4],
                              "sink": parts[5]})
    return methods, edges


def _int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0


def _run_script(script: str, timeout: int) -> str:
    joern = shutil.which(os.environ.get("CODESENTRY_JOERN_BIN", "joern"))
    if joern is None:
        return ""
    with tempfile.NamedTemporaryFile("w", suffix=".sc", delete=False) as handle:
        handle.write(script)
        path = handle.name
    try:
        proc = subprocess.run(
            [joern, "--script", path], capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        return (proc.stdout or "") + "\n" + (proc.stderr or "")
    except Exception:  # noqa: BLE001
        return ""
    finally:
        Path(path).unlink(missing_ok=True)


def run_joern_graph(repo: str, project: str, *, timeout: int = 120) -> dict:
    from codesentry.engines.joern import cpg_path
    from codesentry.rag.graph_delta import apply_engine_graph, resolve_node_key

    cpg = cpg_path(repo)
    if not cpg.is_file():
        return {"ok": False, "error": "cpg missing", "edges": 0}
    out = _run_script(_CALLS_SCRIPT % {"cpg": str(cpg)}, timeout)
    methods, calls = parse_graph_lines(out)
    flow_out = _run_script(_FLOW_SCRIPT % {"cpg": str(cpg)}, timeout)
    _, flows = parse_graph_lines(flow_out)

    nodes = []
    edges = []
    for method in methods:
        key = resolve_node_key(project, method["file"], method["line"], "function")
        if key.startswith(("function:", "method:")):
            nodes.append({"key": key, "kind": "method", "name": method["name"],
                          "path": method["file"], "start": method["line"],
                          "end": method["line"], "qualified_name": method["name"]})
    calls_by_name: dict[str, list[str]] = {}
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT name, node_key FROM graph_nodes WHERE project=%s"
                " AND kind IN ('function','method')", (project,),
            )
            for name, key in cur.fetchall():
                calls_by_name.setdefault(name, []).append(key)
    except Exception:  # noqa: BLE001, S110
        pass
    for call in calls[:5000]:
        src = resolve_node_key(project, call["caller_file"], call["caller_line"], "function")
        if not src.startswith(("function:", "method:")):
            continue
        name = str(call["callee"]).split(".")[-1]
        rows = calls_by_name.get(name) or []
        if len(rows) != 1:
            continue
        edges.append({"src": src, "dst": rows[0], "kind": "calls",
                      "provenance": "joern", "confidence": 0.8,
                      "attrs": {"callee": call["callee"]}})
    for flow in flows:
        src = resolve_node_key(project, flow["source_file"], flow["source_line"], "source")
        dst = resolve_node_key(project, flow["sink_file"], flow["sink_line"], "sink")
        if not src.startswith(("function:", "method:", "file:")):
            continue
        edges.append({"src": src, "dst": dst, "kind": "dataflow",
                      "provenance": "joern", "confidence": 0.7,
                      "attrs": {"source": flow["source"], "sink": flow["sink"]}})
    build_id = 0
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM graph_builds WHERE project=%s ORDER BY id DESC LIMIT 1",
                (project,),
            )
            row = cur.fetchone()
        build_id = int(row[0]) if row else 0
    except Exception:  # noqa: BLE001, S110
        pass
    stats = apply_engine_graph(project, build_id, nodes, edges) if build_id else {}
    return {"ok": True, "methods": len(methods), "calls": len(calls),
            "flows": len(flows), **stats}
