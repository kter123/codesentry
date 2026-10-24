"""路径中心审计：从 sink 反向构建 entry→sink 攻击路径。"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque

EDGE_KINDS = ("contains", "calls", "taints_to", "dataflow", "routes_to", "exposes")


def _path_key(entry: str, source: str, sink: str, nodes: list[str]) -> str:
    raw = "|".join([entry, source, sink, ",".join(nodes)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _score(sink: dict, entry: dict, length: int, tainted: bool) -> float:
    severity = str((sink.get("attrs") or {}).get("severity") or "").lower()
    sev_score = {"critical": 1.0, "high": 0.85, "medium": 0.6, "low": 0.35}.get(severity, 0.5)
    permission = str((entry.get("attrs") or {}).get("permission") or "")
    perm_score = {"内部接口": 1.0, "公开": 0.9, "注册用户": 0.7,
                  "登录用户": 0.6, "管理员权限": 0.35}.get(permission, 0.5)
    short = max(0.0, 1.0 - min(length, 10) / 10.0)
    return round(
        0.35 * sev_score + 0.2 * perm_score + 0.2 * (1.0 if tainted else 0.3)
        + 0.15 * short + 0.1 * (1.0 if tainted else 0.0),
        4,
    )


def _feasibility(nodes: list[dict], edges: list[dict]) -> str:
    if any(e.get("kind") in ("taints_to", "dataflow") for e in edges):
        return "proven"
    if len(nodes) >= 2 and any(e.get("kind") == "calls" for e in edges):
        return "likely"
    return "weak"


def build_paths(
    scan_id: int,
    project: str,
    build_id: int,
    hints: list[dict] | None = None,
    *,
    depth: int = 8,
    max_paths: int = 2000,
    min_score: float = 0.2,
) -> dict:
    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.db.pool import get_conn

    ensure_control_schema()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT node_key, kind, name, path, qualified_name, start_line, end_line, attrs"
            " FROM graph_nodes WHERE project=%s",
            (project,),
        )
        nodes = {
            r[0]: {"key": r[0], "kind": r[1], "name": r[2], "path": r[3],
                   "qualified_name": r[4], "start": r[5], "end": r[6], "attrs": r[7] or {}}
            for r in cur.fetchall()
        }
        cur.execute(
            "SELECT src_key, dst_key, kind FROM graph_edges WHERE project=%s", (project,)
        )
        edges = [{"from": r[0], "to": r[1], "kind": r[2]} for r in cur.fetchall()]

    incoming: dict[str, list[dict]] = defaultdict(list)
    for edge in edges:
        if edge["kind"] in EDGE_KINDS:
            incoming[edge["to"]].append(edge)

    sinks = [n for n in nodes.values() if n["kind"] == "sink"]
    endpoints = [n for n in nodes.values() if n["kind"] == "endpoint"]
    if not sinks and hints:
        # 引擎 hint 未锚定时，用文件级 weak 路径兜底
        for hint in hints[:200]:
            file_path = str(hint.get("file") or "")
            line = int(hint.get("line") or 0)
            if not file_path:
                continue
            sinks.append({"key": f"file:{file_path}", "kind": "sink", "name": file_path,
                          "path": file_path, "start": line, "end": line, "attrs": hint})

    out: list[dict] = []
    seen_keys: set[str] = set()
    per_pair: dict[tuple[str, str], int] = defaultdict(int)

    for sink in sinks[:1000]:
        queue: deque[tuple[str, list[dict], list[str]]] = deque(
            [(sink["key"], [], [sink["key"]])]
        )
        found_entries = 0
        while queue and found_entries < 3:
            current, path_edges, path_nodes = queue.popleft()
            if len(path_edges) >= depth or len(path_nodes) > depth + 1:
                continue
            node = nodes.get(current, sink)
            is_entry = node.get("kind") in ("route", "endpoint") or (
                node.get("kind") in ("function", "method")
                and any(e["from"] == current and e["kind"] == "exposes"
                        for e in edges)
            )
            if is_entry and current != sink["key"]:
                entry = node
                ordered_nodes = list(reversed(path_nodes))
                ordered_edges = list(reversed(path_edges))
                feasibility = _feasibility(
                    [nodes.get(k, {}) for k in ordered_nodes], ordered_edges
                )
                source_key = next(
                    (k for k in ordered_nodes if nodes.get(k, {}).get("kind") == "source"),
                    "",
                )
                if not source_key and feasibility == "proven":
                    source_key = next(
                        (e["from"] for e in ordered_edges if e["kind"] == "taints_to"), ""
                    )
                score = _score(sink, entry, len(ordered_nodes), feasibility == "proven")
                if feasibility == "likely":
                    score *= 0.75
                elif feasibility == "weak":
                    score *= 0.4
                if score < min_score:
                    found_entries += 1
                    continue
                key = _path_key(current, source_key, sink["key"], ordered_nodes)
                pair = (current, sink["key"])
                if key in seen_keys or per_pair[pair] >= 3:
                    found_entries += 1
                    continue
                seen_keys.add(key)
                per_pair[pair] += 1
                found_entries += 1
                out.append({
                    "path_key": key, "kind": "entry_to_sink",
                    "entry_key": current, "source_key": source_key,
                    "sink_key": sink["key"], "nodes": ordered_nodes,
                    "edges": ordered_edges, "length": len(ordered_nodes),
                    "score": score, "feasibility": feasibility,
                })
                if len(out) >= max_paths:
                    break
            for edge in incoming.get(current, []):
                parent = edge["from"]
                if parent in path_nodes:
                    continue
                queue.append((parent, [*path_edges, edge], [*path_nodes, parent]))
        if found_entries == 0 and sink.get("path"):
            same_file = [e for e in endpoints if e.get("path") == sink.get("path")]
            same_dir = [
                e for e in endpoints
                if e.get("path") and sink.get("path")
                and str(e["path"]).rsplit("/", 1)[0] == str(sink["path"]).rsplit("/", 1)[0]
            ]
            for ep in (same_file or same_dir)[:2]:
                ordered_nodes = [ep["key"], sink["key"]]
                key = _path_key(ep["key"], "", sink["key"], ordered_nodes)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                out.append({
                    "path_key": key, "kind": "entry_file",
                    "entry_key": ep["key"], "source_key": "",
                    "sink_key": sink["key"], "nodes": ordered_nodes,
                    "edges": [], "length": 2, "score": max(min_score, 0.25),
                    "feasibility": "weak",
                })
                found_entries += 1
        if len(out) >= max_paths:
            break

    # 入口与 sink 同文件时补充 weak 路径，避免调用边缺失导致覆盖过低
    for ep in endpoints[:300]:
        if len(out) >= max_paths:
            break
        if 0.25 < min_score:
            break
        same_file = [s for s in sinks if s.get("path") and s.get("path") == ep.get("path")]
        for sink in same_file[:5]:
            path_nodes = [ep["key"], sink["key"]]
            key = _path_key(ep["key"], "", sink["key"], path_nodes)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            out.append({
                "path_key": key, "kind": "entry_file",
                "entry_key": ep["key"], "source_key": "",
                "sink_key": sink["key"], "nodes": path_nodes, "edges": [],
                "length": 2, "score": max(min_score, 0.25), "feasibility": "weak",
            })

    # 同目录（同包）入口 → sink：补跨文件调用边缺失导致的覆盖空洞
    if 0.22 >= min_score:
        for sink in sinks[:300]:
            if len(out) >= max_paths:
                break
            sink_dir = str(sink.get("path") or "").rsplit("/", 1)[0]
            if not sink_dir:
                continue
            same_dir = [
                e for e in endpoints
                if e.get("path") and str(e["path"]).rsplit("/", 1)[0] == sink_dir
            ]
            for ep in same_dir[:2]:
                path_nodes = [ep["key"], sink["key"]]
                key = _path_key(ep["key"], "", sink["key"], path_nodes)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                out.append({
                    "path_key": key, "kind": "entry_package",
                    "entry_key": ep["key"], "source_key": "",
                    "sink_key": sink["key"], "nodes": path_nodes, "edges": [],
                    "length": 2, "score": max(min_score, 0.22), "feasibility": "weak",
                })

    # 同模块（业务包）入口 → sink：补跨包调用边缺失
    if 0.21 >= min_score:
        for sink in sinks[:400]:
            if len(out) >= max_paths:
                break
            module = _module_of(str(sink.get("path") or ""))
            if not module:
                continue
            module_eps = [e for e in endpoints if _module_of(str(e.get("path") or "")) == module]
            for ep in module_eps[:2]:
                path_nodes = [ep["key"], sink["key"]]
                key = _path_key(ep["key"], "", sink["key"], path_nodes)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                out.append({
                    "path_key": key, "kind": "entry_module",
                    "entry_key": ep["key"], "source_key": "",
                    "sink_key": sink["key"], "nodes": path_nodes, "edges": [],
                    "length": 2, "score": max(min_score, 0.21), "feasibility": "weak",
                })

    # 没有可达 sink 的入口也要审计（鉴权/参数/越权），标 entry_only 弱路径
    covered_entries = {p["entry_key"] for p in out}
    if 0.2 >= min_score:
        for ep in endpoints:
            if ep["key"] in covered_entries:
                continue
            key = _path_key(ep["key"], "", "", [ep["key"]])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            out.append({
                "path_key": key, "kind": "entry_only",
                "entry_key": ep["key"], "source_key": "", "sink_key": "",
                "nodes": [ep["key"]], "edges": [], "length": 1,
                "score": max(min_score, 0.2), "feasibility": "weak",
                "file": ep.get("path", ""), "line": ep.get("start", 0),
            })
            if len(out) >= max_paths:
                break

    inserted = 0
    with get_conn() as conn, conn.cursor() as cur:
        for path in out:
            cur.execute(
                "INSERT INTO audit_paths (scan_id, path_key, round, kind, entry_key,"
                " source_key, sink_key, nodes, edges, length, score, feasibility, status)"
                " VALUES (%s,%s,0,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,'pending')"
                " ON CONFLICT (scan_id, path_key) DO NOTHING",
                (scan_id, path["path_key"], path["kind"], path["entry_key"],
                 path["source_key"], path["sink_key"],
                 json.dumps(path["nodes"]), json.dumps(path["edges"]),
                 path["length"], path["score"], path["feasibility"]),
            )
            inserted += cur.rowcount
        conn.commit()
    coverage = _coverage(nodes, out)
    return {"candidates": len(out), "inserted": inserted, "coverage": coverage}


def _module_of(path: str) -> str:
    parts = path.split("/")
    if "modules" in parts:
        idx = parts.index("modules")
        if idx + 1 < len(parts):
            return "/".join(parts[: idx + 2])
    # 非 modules 结构：取前 6 段作为包边界
    return "/".join(parts[:6]) if len(parts) > 5 else ""


def _coverage(nodes: dict, paths: list[dict]) -> dict:
    endpoints = [n for n in nodes.values() if n["kind"] == "endpoint"]
    sinks = [n for n in nodes.values() if n["kind"] == "sink"]
    covered_entries = {p["entry_key"] for p in paths}
    endpoint_keys = {n["key"] for n in endpoints}
    covered_endpoints = covered_entries & endpoint_keys
    covered_sinks = {p["sink_key"] for p in paths}
    return {
        "endpoints": len(endpoints),
        "endpoints_covered": len(covered_endpoints),
        "sinks": len(sinks),
        "sinks_covered": len(covered_sinks),
        "paths": len(paths),
        "dataflow_paths": sum(
            1 for p in paths if any(e.get("kind") == "dataflow" for e in (p.get("edges") or []))
        ),
    }
