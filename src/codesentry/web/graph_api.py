"""M5.2 图审阅 API：findings + 合成调用图 + 源码切片。"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException, Query

from codesentry.db.pool import get_conn


def _work_root() -> Path:
    return Path(os.environ.get("CODESENTRY_WORK_DIR", "work")).resolve()


def _route():
    from codesentry.web.server import app as _app

    return _app


app = _route()


def _scan_repo(scan_id: int) -> Path:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT repo_path FROM scans WHERE id=%s", (scan_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "scan not found")
    p = Path(row[0]).resolve()
    if _work_root() not in p.parents:
        raise HTTPException(400, "repo outside work root")
    return p


@app.get("/api/scans/{scan_id}/graph")
async def get_graph(scan_id: int, limit: int = Query(1200, ge=100, le=10000)) -> dict:
    """真实代码图：graph_nodes/graph_edges + findings 锚定 + endpoint 资产。"""
    repo = _scan_repo(scan_id)
    project = str(repo)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, rule_id, cwe, severity, confidence, file, line, message, engine, verdict"
            " FROM findings WHERE scan_id=%s",
            (scan_id,),
        )
        findings = cur.fetchall()
        cur.execute(
            "SELECT node_key, kind, name, path, qualified_name, start_line, end_line, lang"
            " FROM graph_nodes WHERE project=%s"
            " ORDER BY CASE kind WHEN 'endpoint' THEN 0 WHEN 'route' THEN 1"
            " WHEN 'function' THEN 2 WHEN 'method' THEN 3 WHEN 'class' THEN 4"
            " WHEN 'file' THEN 5 ELSE 6 END, id LIMIT %s",
            (project, limit),
        )
        node_rows = cur.fetchall()
        cur.execute(
            "SELECT src_key, dst_key, kind, provenance, confidence FROM graph_edges"
            " WHERE project=%s LIMIT %s",
            (project, limit * 4),
        )
        edge_rows = cur.fetchall()
        cur.execute(
            "SELECT endpoint_key, method, route, permission, path, line, evidence, mismatch"
            " FROM graph_endpoints WHERE project=%s ORDER BY route, method",
            (project,),
        )
        endpoint_rows = cur.fetchall()
        cur.execute("SELECT graph_build_id FROM scans WHERE id=%s", (scan_id,))
        build_row = cur.fetchone()

    fcols = ["id", "rule_id", "cwe", "severity", "confidence", "file", "line",
             "message", "engine", "verdict"]
    by_file: dict[str, list[dict]] = {}
    for r in findings:
        f = dict(zip(fcols, r))
        try:
            f["file_rel"] = str(Path(f["file"]).resolve().relative_to(repo))
        except ValueError:
            f["file_rel"] = Path(f["file"]).name
        by_file.setdefault(f["file_rel"], []).append(f)

    nodes: dict[str, dict] = {}
    for key, kind, name, path, qual, start, end, lang in node_rows:
        nodes[key] = {
            "id": key, "key": key, "kind": kind, "name": name, "file": path,
            "qualified_name": qual, "start": start, "end": end, "lang": lang,
            "findings": [],
        }
    for file_path, items in by_file.items():
        candidates = [n for n in nodes.values() if n["file"] == file_path]
        for f in items:
            line = int(f.get("line") or 0)
            container = [n for n in candidates if n["start"] <= line <= n["end"]]
            target = min(container, key=lambda n: n["end"] - n["start"]) if container else None
            if target is None:
                target = next((n for n in candidates if n["kind"] in ("file", "endpoint")), None)
            if target is not None:
                target["findings"].append(f)

    edges = [
        {"source": s, "target": d, "kind": k, "provenance": p, "confidence": c}
        for s, d, k, p, c in edge_rows
    ]
    endpoints = [
        {"key": r[0], "method": r[1], "route": r[2], "permission": r[3],
         "file": r[4], "line": r[5], "evidence": r[6], "mismatch": r[7]}
        for r in endpoint_rows
    ]
    from codesentry.scan_orchestrator import detect_languages

    langs = detect_languages(str(repo))
    mode = "graph" if nodes else "findings-only"
    if not nodes and by_file:
        for file_path, items in by_file.items():
            nid = "file::" + file_path
            nodes[nid] = {"id": nid, "key": nid, "kind": "file", "file": file_path,
                          "name": Path(file_path).name, "start": 0, "end": 0,
                          "findings": items}
    return {
        "scan_id": scan_id, "mode": mode, "languages": langs,
        "graph_build_id": build_row[0] if build_row else None,
        "nodes": list(nodes.values()), "edges": edges, "endpoints": endpoints,
    }


@app.get("/api/scans/{scan_id}/graph/endpoints")
async def graph_endpoints(scan_id: int, permission: str = "") -> dict:
    repo = _scan_repo(scan_id)
    from codesentry.rag.graph_query import entrypoints

    return {"scan_id": scan_id, "endpoints": entrypoints(str(repo), permission or None)}


@app.get("/api/scans/{scan_id}/graph/paths")
async def graph_paths(scan_id: int, src: str = Query(...), dst: str = Query(...),
                      max_depth: int = Query(6, ge=1, le=8)) -> dict:
    repo = _scan_repo(scan_id)
    from codesentry.rag.graph_query import paths

    return {"scan_id": scan_id, "paths": paths(str(repo), src, dst, max_depth=max_depth)}


@app.get("/api/scans/{scan_id}/graph/node/{key:path}")
async def graph_node(scan_id: int, key: str) -> dict:
    repo = _scan_repo(scan_id)
    from codesentry.rag.graph_query import neighbors, node

    found = node(str(repo), key)
    if not found:
        raise HTTPException(404, "node not found")
    return {"scan_id": scan_id, "node": found,
            "neighbors": neighbors(str(repo), key, depth=1)}


@app.get("/api/scans/{scan_id}/findings")
async def list_scan_findings(scan_id: int) -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, rule_id, cwe, severity, confidence, file, line, message, engine,
                      verdict, poc_path, verification_method, confidence_parts, tool_trace
               FROM findings WHERE scan_id=%s ORDER BY id""",
            (scan_id,),
        )
        rows = cur.fetchall()
    cols = ["id", "rule_id", "cwe", "severity", "confidence", "file", "line", "message",
            "engine", "verdict", "poc_path", "verification_method", "confidence_parts", "tool_trace"]
    return {"scan_id": scan_id, "findings": [dict(zip(cols, r)) for r in rows]}


@app.get("/api/findings/{finding_id}")
async def get_finding(finding_id: int) -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, scan_id, rule_id, cwe, severity, confidence, file, line, message, engine,
                      taint_metadata, exploit_chain, poc_path, verdict, execution_log,
                      verification_method, verification_nonce, confidence_parts, tool_trace
               FROM findings WHERE id=%s""",
            (finding_id,),
        )
        r = cur.fetchone()
        if not r:
            raise HTTPException(404)
    cols = ["id", "scan_id", "rule_id", "cwe", "severity", "confidence", "file", "line", "message", "engine",
            "taint_metadata", "exploit_chain", "poc_path", "verdict", "execution_log",
            "verification_method", "verification_nonce", "confidence_parts", "tool_trace"]
    return dict(zip(cols, r))


@app.get("/api/scans/{scan_id}/source")
async def get_source(
    scan_id: int,
    path: str = Query(...),
    start: int = Query(1, ge=1),
    end: int = Query(50, le=2000),
) -> dict:
    """源码切片（带行号），防路径穿越：仅 work/{scan}/ 下文件。"""
    repo = _scan_repo(scan_id)
    target = (repo / path).resolve()
    if repo not in target.parents and target != repo:
        raise HTTPException(400, "path escapes repo")
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise HTTPException(404, f"cannot read: {e}") from e
    lines = text.splitlines()
    window = lines[start - 1 : end]
    return {
        "path": path, "start": start, "end": min(end, start - 1 + len(window)),
        "total_lines": len(lines),
        "lines": [{"no": start + i, "text": t} for i, t in enumerate(window)],
    }


@app.get("/api/scans/{scan_id}/paths")
async def list_audit_paths(scan_id: int, status: str = "", round: int | None = None,
                           limit: int = 100) -> dict:
    from codesentry.control.audit_paths import list_paths

    return {"scan_id": scan_id,
            "paths": list_paths(scan_id, status or None, round, limit)}


@app.get("/api/scans/{scan_id}/paths/{path_id}")
async def get_audit_path(scan_id: int, path_id: int) -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, path_key, round, kind, entry_key, source_key, sink_key, nodes,"
            " edges, length, score, feasibility, status, finding_id, evidence"
            " FROM audit_paths WHERE scan_id=%s AND id=%s",
            (scan_id, path_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "path not found")
    keys = ["id", "path_key", "round", "kind", "entry_key", "source_key", "sink_key",
            "nodes", "edges", "length", "score", "feasibility", "status",
            "finding_id", "evidence"]
    return dict(zip(keys, row))


@app.get("/api/scans/{scan_id}/coverage")
async def audit_coverage(scan_id: int) -> dict:
    from codesentry.control.audit_paths import coverage

    return {"scan_id": scan_id, **coverage(scan_id)}
