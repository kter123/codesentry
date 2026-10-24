"""GraphBuild 节点：把仓库解析成可检索的代码图（G1）。"""

from __future__ import annotations

import threading


def run_graph_build(state: dict) -> dict:
    repo = str(state.get("repo_path") or "")
    if not repo:
        return {"graph_stats": {"ok": False, "error": "repo_path 为空"}, "phase": "graph_build"}
    diff = state.get("diff_scope") or None
    mode = "diff" if diff else "full"
    changed = diff.get("files") if isinstance(diff, dict) else None
    try:
        from codesentry.rag.graph_build import build_graph

        result = build_graph(repo, mode=mode, changed_files=changed)
    except Exception as exc:  # noqa: BLE001 - 图不可用不阻塞扫描
        return {
            "graph_stats": {"ok": False, "error": str(exc)[:300]},
            "messages": [f"graph_build: 降级（{str(exc)[:160]}）"],
            "phase": "graph_build",
        }
    sid = int(state.get("scan_id") or 0)
    stats = result.get("stats") or {}
    if sid:
        try:
            from codesentry.db.pool import get_conn

            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE scans SET graph_build_id=%s WHERE id=%s",
                    (int(result["build_id"]), sid),
                )
                conn.commit()
        except Exception:  # noqa: BLE001, S110 - 台账失败不影响扫描
            pass
    try:
        from codesentry.config import get_settings

        if get_settings().index_on_graph_build:
            threading.Thread(
                target=_index_async, args=(repo, result.get("changed")), daemon=True
            ).start()
            stats = {**stats, "index_async": True}
    except Exception as exc:  # noqa: BLE001 - 索引失败不阻塞建图
        stats = {**stats, "index_error": str(exc)[:160]}
    return {
        "graph_build_id": int(result["build_id"]),
        "graph_stats": stats,
        "phase": "graph_build",
    }


def _index_async(repo: str, files: list[str] | None) -> None:
    try:
        from codesentry.rag.indexer import index_repo

        index_repo(repo, files=files)
    except Exception:  # noqa: BLE001, S110 - 后台索引失败不影响扫描
        pass
