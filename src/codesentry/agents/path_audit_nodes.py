"""LangGraph 路径审计节点：path_build → audit_plan → audit_path(Send) → collect。"""

from __future__ import annotations

import json
from pathlib import Path


def run_path_build(state: dict) -> dict:
    from codesentry.config import get_settings
    from codesentry.rag.path_build import build_paths

    scan_id = int(state.get("scan_id") or 0)
    if scan_id <= 0:
        return {"coverage": {}, "audit_round": 0}
    repo = str(state.get("repo_path") or "")
    project = str(Path(repo).resolve())
    result = build_paths(
        scan_id, project,
        int(state.get("graph_build_id") or 0),
        list(state.get("engine_hints") or []),
        depth=get_settings().path_depth,
        max_paths=get_settings().max_paths,
        min_score=get_settings().path_min_score,
    )
    return {
        "coverage": result.get("coverage") or {},
        "audit_round": 0,
        "messages": [*(state.get("messages") or []),
                     f"path_build: {result.get('inserted', 0)} paths"],
    }


def run_audit_plan(state: dict) -> dict:
    from codesentry.config import get_settings
    from codesentry.control.audit_paths import claim_paths, reclaim_expired

    scan_id = int(state.get("scan_id") or 0)
    if scan_id <= 0:
        return {"audit_paths": []}
    reclaim_expired(scan_id, get_settings().path_lease_s)
    paths = claim_paths(
        scan_id, get_settings().audit_batch, get_settings().path_lease_s,
        max_paths=get_settings().audit_max_paths,
        entry_only_max=get_settings().audit_entry_only_max,
        priority=get_settings().audit_priority,
        max_attempts=get_settings().audit_path_attempts_max,
    )
    return {"audit_paths": paths}


def route_audit(state: dict):
    from langgraph.types import Send

    paths = state.get("audit_paths") or []
    if paths:
        base = {k: v for k, v in state.items() if k not in ("audit_paths", "path_results")}
        return [Send("audit_path", {**base, "path": p}) for p in paths]
    return "triage"


def _persist_live_finding(scan_id: int, finding: dict) -> None:
    finding = {**finding, "path_id": finding.get("path_id")}
    if not scan_id or not finding.get("path_id"):
        return
    try:
        from codesentry.db.pool import get_conn

        taint = {**(finding.get("taint_metadata") or {}), "live": True}
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO findings (scan_id, rule_id, cwe, severity, confidence, file,"
                " line, message, engine, taint_metadata, path_id, verdict)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,'candidate')"
                " ON CONFLICT (scan_id, path_id) WHERE path_id IS NOT NULL"
                " DO UPDATE SET rule_id=EXCLUDED.rule_id, cwe=EXCLUDED.cwe,"
                " severity=EXCLUDED.severity, confidence=EXCLUDED.confidence,"
                " file=EXCLUDED.file, line=EXCLUDED.line, message=EXCLUDED.message,"
                " engine=EXCLUDED.engine, taint_metadata=EXCLUDED.taint_metadata,"
                " verdict='candidate'",
                (int(scan_id), finding.get("rule_id"), int(finding.get("cwe") or 610),
                 str(finding.get("severity") or "medium"),
                 float(finding.get("confidence") or 0.5), str(finding.get("file") or ""),
                 max(1, int(finding.get("line") or 1)), str(finding.get("message") or "")[:500],
                 str(finding.get("engine") or "agent"), json.dumps(taint),
                 int(finding["path_id"])),
            )
            conn.commit()
        try:
            from codesentry.orchestrator.events import publish_event

            publish_event(scan_id, "finding.candidate", agent="audit", phase="path_audit",
                          payload={"rule_id": finding.get("rule_id"),
                                   "cwe": finding.get("cwe"),
                                   "path_id": finding.get("path_id"),
                                   "severity": finding.get("severity")})
        except Exception:  # noqa: BLE001, S110
            pass
    except Exception:  # noqa: BLE001, S110 - 实时落库失败不影响路径审计
        pass


def run_audit_path(state: dict, runtime=None) -> dict:
    from codesentry.agents.path_audit import run_path_audit
    from codesentry.control.audit_paths import finish_path

    path = state.get("path") or {}
    result = run_path_audit(state, path, runtime=runtime)
    if path.get("kind") == "entry_only":
        try:
            from codesentry.rag.graph_query import node as graph_node

            entry = graph_node(str(Path(str(state.get("repo_path") or "")).resolve()),
                               str(path.get("entry_key") or ""))
            if entry:
                path = {**path, "file": entry.get("path"), "line": entry.get("start")}
        except Exception:  # noqa: BLE001, S110
            pass
    reason = str(result.get("reason") or "")
    status = {
        "finding": "finding", "clean": "clean", "blocked": "blocked",
        "need_more": "pending",
    }.get(str(result.get("verdict")), "pending")
    if status == "pending" and "超时" in reason:
        status = "timeout"
    elif status == "pending" and ("审计失败" in reason or "失败：" in reason):
        status = "error"
    finding = _to_finding(path, result) if status == "finding" else None
    if finding:
        finding["path_id"] = path.get("id")
        _persist_live_finding(int(state.get("scan_id") or 0), finding)
    finish_path(int(path.get("id") or 0), status,
                {**result, "finding_id": None,
                 "finding": finding} if finding else result)
    try:
        from codesentry.orchestrator.events import publish_event

        publish_event(int(state.get("scan_id") or 0), "path.audited", agent="audit",
                      phase="path_audit",
                      payload={"path_id": path.get("id"), "status": status,
                               "reason": reason[:200]})
    except Exception:  # noqa: BLE001, S110
        pass
    return {
        "path_results": [{"path_id": path.get("id"), "status": status,
                          "finding": finding, "verdict": result.get("verdict")}],
    }


def run_audit_collect(state: dict) -> dict:
    from codesentry.config import get_settings
    from codesentry.control.audit_paths import enqueue_paths, sibling_paths

    repo = str(state.get("repo_path") or "")
    project = str(Path(repo).resolve())
    batch_no = int(state.get("audit_batch") or 0) + 1
    expand_round = int(state.get("audit_round") or 0) + 1
    paths = []
    for item in state.get("path_results") or []:
        if item.get("status") not in ("finding", "pending"):
            continue
        path = next((p for p in (state.get("audit_paths") or [])
                     if p.get("id") == item.get("path_id")), None)
        if path is None:
            continue
        # 只对 finding 或首轮 proven 未决路径做兄弟扩展；避免无 LLM 时
        # need_more → sibling → need_more 的指数膨胀。
        if item.get("status") == "pending" and (
            path.get("feasibility") != "proven" or int(path.get("round") or 0) > 0
        ):
            continue
        if path:
            paths.extend(sibling_paths(project, path))
    inserted = (enqueue_paths(int(state.get("scan_id") or 0), paths, expand_round)
                if paths else 0)
    # 只有产生了新的扩展路径才推进“轮次”；否则只是在同一轮内消费批次
    round_no = expand_round if inserted else int(state.get("audit_round") or 0)
    settings = get_settings()
    _write_round(int(state.get("scan_id") or 0), round_no, inserted, state, batch_no)
    try:
        from codesentry.control.audit_paths import coverage as _coverage

        cover = _coverage(int(state.get("scan_id") or 0))
    except Exception:  # noqa: BLE001
        cover = {}
    candidates: list[dict] = []
    seen: set[tuple] = set()
    for item in state.get("path_results") or []:
        finding = item.get("finding")
        if not finding:
            if item.get("status") == "pending":
                path = next((p for p in (state.get("audit_paths") or [])
                             if p.get("id") == item.get("path_id")), None)
                if path and path.get("feasibility") == "proven":
                    finding = _to_finding(path, {
                        "cwe": 610, "severity": "medium", "confidence": 0.35,
                        "reason": "proven 路径未完成判定，按待复查候选保留",
                    })
                    finding["path_id"] = path.get("id")
            if not finding:
                continue
        key = (finding.get("rule_id"), finding.get("file"), finding.get("line"))
        if key in seen:
            continue
        seen.add(key)
        candidates.append(finding)
    merged: dict[tuple, dict] = {}
    for finding in [*(state.get("candidate_findings") or []), *candidates]:
        merged[(finding.get("rule_id"), finding.get("file"), finding.get("line"))] = finding
    return {
        "candidate_findings": list(merged.values()),
        "audit_paths": [],
        "audit_round": round_no,
        "audit_batch": batch_no,
        "messages": [*(state.get("messages") or []),
                     f"audit batch {batch_no} (round {round_no}): +{inserted} paths"],
        "coverage": {
            **(state.get("coverage") or {}),
            **cover,
            "round": round_no,
            "batch": batch_no,
            "new_paths": inserted,
            "pending": cover.get("pending", 0),
            "max_rounds": settings.audit_max_rounds,
        },
    }


def route_after_collect(state: dict) -> str:
    from codesentry.config import get_settings

    if (state.get("budget") or {}).get("phase") == "breach":
        return "triage"
    round_no = int(state.get("audit_round") or 0)
    if round_no >= get_settings().audit_max_rounds:
        return "triage"
    return "audit_plan"


def _hint_for_path(state: dict, path: dict) -> dict:
    sink = str(path.get("sink_key") or "")
    file = ""
    line = 0
    path_part = sink.split("#", 1)[0]
    for prefix in ("sink:", "function:", "method:", "source:"):
        if path_part.startswith(prefix):
            file = path_part[len(prefix):]
            break
    try:
        if "@" in sink:
            line = int(sink.rsplit("@", 1)[-1])
    except ValueError:
        line = 0
    for hint in state.get("engine_hints") or []:
        if not hint.get("file") or not hint.get("line"):
            continue
        if str(hint["file"]) == file and int(hint["line"]) == line:
            return hint
    return {}


def run_audit_finalize(state: dict) -> dict:
    from codesentry.control.audit_paths import list_paths

    scan_id = int(state.get("scan_id") or 0)
    if scan_id <= 0:
        return {"candidate_findings": [], "phase": "triage"}
    paths = list_paths(scan_id, status="finding", limit=500)
    candidates = []
    for path in paths:
        finding = (path.get("evidence") or {}).get("finding")
        if not finding:
            continue
        candidates.append({**finding, "path_id": path["id"],
                           "path_nodes": path.get("nodes"),
                           "taint_metadata": {"path_id": path["id"],
                                              "path_nodes": path.get("nodes")}})
    # 未完成但可行性较高的路径作为低置信候选，交给 Triage 判定，避免静默丢失
    for path in list_paths(scan_id, status="pending", limit=50):
        if path.get("feasibility") not in ("proven", "likely"):
            continue
        evidence = path.get("evidence") or {}
        hint = _hint_for_path(state, path)
        candidates.append({
            **_to_finding(path, {
                "cwe": hint.get("cwe") or evidence.get("cwe") or 610,
                "severity": hint.get("severity") or evidence.get("severity") or "medium",
                "confidence": min(float(evidence.get("confidence") or 0.4), 0.4),
                "reason": hint.get("message") or evidence.get("reason")
                or "路径未完成审计，按可疑保留",
                "fix_advice": evidence.get("fix_advice") or "",
                "engine_hint": hint or None,
            }),
            "path_id": path["id"], "path_nodes": path.get("nodes"),
            "taint_metadata": {
                "path_id": path["id"], "path_nodes": path.get("nodes"),
                "engine_hint": hint or None,
            },
        })
    return {
        "candidate_findings": candidates,
        "audit": {**(state.get("audit") or {}), "path_findings": len(candidates)},
        "phase": "triage",
    }


def _write_round(scan_id: int, round_no: int, new_paths: int, state: dict,
                 batch_no: int = 0) -> None:
    try:
        from codesentry.db.pool import get_conn

        results = state.get("path_results") or []
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM audit_paths WHERE scan_id=%s", (scan_id,))
            total = int(cur.fetchone()[0])
            cur.execute(
                "INSERT INTO audit_rounds (scan_id, round, paths_total, paths_new,"
                " paths_audited, findings, batch, finished_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,now())"
                " ON CONFLICT (scan_id, round) DO UPDATE SET paths_total=EXCLUDED.paths_total,"
                " paths_new=EXCLUDED.paths_new, paths_audited=EXCLUDED.paths_audited,"
                " findings=EXCLUDED.findings, batch=EXCLUDED.batch, finished_at=now()",
                (scan_id, round_no, total, new_paths, len(results), batch_no,
                 sum(1 for r in results if r.get("status") == "finding")),
            )
            conn.commit()
    except Exception:  # noqa: BLE001, S110 - 统计失败不影响审计
        pass


def _to_finding(path: dict, result: dict) -> dict:
    nodes = path.get("nodes") or []
    sink = nodes[-1] if nodes else ""
    file = str(path.get("file") or "")
    line = int(path.get("line") or 0)
    if not file:
        path_part = sink.split("#", 1)[0]
        for prefix in ("sink:", "function:", "method:", "source:"):
            if path_part.startswith(prefix):
                file = path_part[len(prefix):]
                break
    try:
        if not line and "@" in str(sink):
            line = int(str(sink).rsplit("@", 1)[-1])
    except ValueError:
        line = 0
    return {
        "rule_id": f"path.{result.get('cwe') or 610}",
        "cwe": int(result.get("cwe") or 610),
        "severity": str(result.get("severity") or "medium"),
        "confidence": float(result.get("confidence") or 0.6),
        "file": file or sink,
        "line": max(1, line),
        "message": str(result.get("reason") or "路径审计发现")[:500],
        "engine": "agent",
        "fix_advice": str(result.get("fix_advice") or ""),
        "taint_metadata": {
            "path_id": path.get("id"), "path_nodes": nodes,
            "evidence": result.get("evidence") or [],
        },
    }
