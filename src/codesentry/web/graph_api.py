"""M5.2 图审阅 API：findings + 合成调用图 + 源码切片。"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException, Query

from codesentry.db.pool import get_conn
from codesentry.rag.chunker import chunk_code


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
async def get_graph(scan_id: int) -> dict:
    """合成调用图：节点=file/function，边=CALLS，findings 挂 sink 节点。"""
    repo = _scan_repo(scan_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, rule_id, cwe, severity, confidence, file, line, message, engine, verdict FROM findings WHERE scan_id=%s",
            (scan_id,),
        )
        findings = cur.fetchall()

    fcols = ["id", "rule_id", "cwe", "severity", "confidence", "file", "line", "message", "engine", "verdict"]
    finding_by_file: dict[str, list] = {}
    for r in findings:
        f = dict(zip(fcols, r))
        finding_by_file.setdefault(f["file"], []).append(f)
        # 相对化
        try:
            f["file_rel"] = str(Path(f["file"]).resolve().relative_to(repo))
        except ValueError:
            f["file_rel"] = Path(f["file"]).name

    # 合成图：python 仓库用 chunker；其他语言 findings-only 退化图
    from codesentry.scan_orchestrator import detect_languages

    langs = detect_languages(str(repo))
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    if "python" in langs:
        for root, _dirs, files in os.walk(repo):
            for name in files:
                if not name.endswith(".py"):
                    continue
                p = Path(root) / name
                try:
                    src = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                rel = str(p.relative_to(repo))
                for c in chunk_code(str(p), "python", src):
                    if c.symbol_kind != "function":
                        continue
                    nid = rel + "::" + c.symbol_name
                    nodes[nid] = {
                        "id": nid, "kind": "function", "file": rel,
                        "name": c.symbol_name, "start": c.start_line, "end": c.end_line,
                        "findings": [],
                    }
                    for callee in (c.call_refs or [])[:20]:
                        edges.append({"source": nid, "target": callee, "kind": "CALLS"})

    # findings 挂到所属 function 节点（文件内行号匹配特征）；否则挂 file 节点
    for filek, fs in finding_by_file.items():
        targets = [nid for nid, n in nodes.items() if n["file"] == filek]
        pick = None
        for f in fs:
            ln = f["line"] or 0
            pick = next((t for t in targets if nodes[t]["start"] <= ln <= nodes[t]["end"]), targets[0] if targets else None)
            if pick:
                nodes[pick]["findings"].append(f)

    graph_mode = "callgraph" if "python" in langs else "findings-only"
    if not nodes and finding_by_file:
        for filek, fs in finding_by_file.items():
            nid = "file::" + filek
            nodes[nid] = {"id": nid, "kind": "file", "file": filek, "name": Path(filek).name,
                          "start": 0, "end": 0, "findings": fs}
        graph_mode = "findings-only"
    return {
        "scan_id": scan_id, "mode": graph_mode, "languages": langs,
        "nodes": list(nodes.values()), "edges": edges,
    }


@app.get("/api/scans/{scan_id}/findings")
async def list_scan_findings(scan_id: int) -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, rule_id, cwe, severity, confidence, file, line, message, engine,
                      verdict, poc_path, verification_method, confidence_parts
               FROM findings WHERE scan_id=%s ORDER BY id""",
            (scan_id,),
        )
        rows = cur.fetchall()
    cols = ["id", "rule_id", "cwe", "severity", "confidence", "file", "line", "message",
            "engine", "verdict", "poc_path", "verification_method", "confidence_parts"]
    return {"scan_id": scan_id, "findings": [dict(zip(cols, r)) for r in rows]}


@app.get("/api/findings/{finding_id}")
async def get_finding(finding_id: int) -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, scan_id, rule_id, cwe, severity, confidence, file, line, message, engine,
                      taint_metadata, exploit_chain, poc_path, verdict, execution_log,
                      verification_method, verification_nonce, confidence_parts
               FROM findings WHERE id=%s""",
            (finding_id,),
        )
        r = cur.fetchone()
        if not r:
            raise HTTPException(404)
    cols = ["id", "scan_id", "rule_id", "cwe", "severity", "confidence", "file", "line", "message", "engine",
            "taint_metadata", "exploit_chain", "poc_path", "verdict", "execution_log",
            "verification_method", "verification_nonce", "confidence_parts"]
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
