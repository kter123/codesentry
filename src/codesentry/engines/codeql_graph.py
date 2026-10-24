"""CodeQL SARIF codeFlows → 图增量 dataflow 边。"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from urllib.parse import unquote, urlparse


def normalize_sarif_uri(uri: str, repo: str) -> str:
    text = unquote(str(uri or ""))
    if text.startswith("file://"):
        text = urlparse(text).path
    path = Path(text)
    try:
        if path.is_absolute():
            return str(path.resolve().relative_to(Path(repo).resolve()))
    except ValueError:
        return ""
    return text.lstrip("./")


def parse_codeql_flows(doc: dict, repo: str) -> list[dict]:
    edges: list[dict] = []
    for run in doc.get("runs", []) or []:
        for result in run.get("results", []) or []:
            for flow in result.get("codeFlows", []) or []:
                for thread in flow.get("threadFlows", []) or []:
                    locations = []
                    for item in thread.get("locations", []) or []:
                        loc = (item or {}).get("location") or {}
                        physical = loc.get("physicalLocation") or {}
                        uri = (physical.get("artifactLocation") or {}).get("uri", "")
                        line = ((physical.get("region") or {}).get("startLine") or 0)
                        path = normalize_sarif_uri(uri, repo)
                        if path and line:
                            locations.append({"path": path, "line": int(line)})
                    for src, dst in itertools.pairwise(locations):
                        if (src["path"], src["line"]) == (dst["path"], dst["line"]):
                            continue
                        edges.append({"src_path": src["path"], "src_line": src["line"],
                                      "dst_path": dst["path"], "dst_line": dst["line"]})
                    if len(locations) > 2:
                        first, last = locations[0], locations[-1]
                        edges.append({"src_path": first["path"], "src_line": first["line"],
                                      "dst_path": last["path"], "dst_line": last["line"]})
    return edges


def run_codeql_graph(sarif_path: str, repo: str, project: str) -> dict:
    try:
        doc = json.loads(Path(sarif_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc)[:200], "edges": 0}
    raw = parse_codeql_flows(doc, repo)
    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.db.pool import get_conn
    from codesentry.rag.graph_delta import apply_engine_graph, resolve_node_key

    ensure_control_schema()
    edges = []
    for item in raw[:5000]:
        src = resolve_node_key(project, item["src_path"], item["src_line"], "source")
        dst = resolve_node_key(project, item["dst_path"], item["dst_line"], "sink")
        edges.append({"src": src, "dst": dst, "kind": "dataflow",
                      "provenance": "codeql", "confidence": 0.9,
                      "attrs": {"src": item["src_path"], "src_line": item["src_line"],
                                "dst": item["dst_path"], "dst_line": item["dst_line"]}})
    build_id = 0
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM graph_builds WHERE project=%s ORDER BY id DESC LIMIT 1",
                (project,),
            )
            row = cur.fetchone()
        build_id = int(row[0]) if row else 0
    except Exception:  # noqa: BLE001, S110
        pass
    stats = apply_engine_graph(project, build_id, [], edges) if build_id else {}
    return {"ok": True, "flows": len(raw), **stats}
