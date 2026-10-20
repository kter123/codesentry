"""Agent Artifacts 审查链（M6.4）：输入/输出摘要 + 哈希链。"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _digest(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _preview(obj: Any, limit: int = 4096) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)[:limit]


def write_artifact(
    *,
    scan_id: int,
    seq: int,
    node: str,
    input_obj: Any,
    output_obj: Any,
    model: str = "",
    tokens: int = 0,
    prev_sha256: str = "",
) -> str | None:
    """写入一条 artifact，返回 output_digest；失败返回 None。"""
    try:
        from codesentry.db.pool import get_conn

        out_digest = _digest(output_obj)
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_artifacts
                    (scan_id, seq, node, input_preview, output_preview,
                     input_digest, output_digest, model, tokens, prev_sha256)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (scan_id, seq) DO NOTHING
                """,
                (
                    int(scan_id), int(seq), node, _preview(input_obj), _preview(output_obj),
                    _digest(input_obj), out_digest, model, int(tokens), prev_sha256 or "",
                ),
            )
            conn.commit()
        return out_digest
    except Exception:  # noqa: BLE001
        return None


def list_artifacts(scan_id: int) -> list[dict]:
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT seq, node, input_preview, output_preview, input_digest, output_digest,"
                " model, tokens, prev_sha256, created_at FROM agent_artifacts"
                " WHERE scan_id=%s ORDER BY seq",
                (int(scan_id),),
            )
            rows = cur.fetchall()
        return [
            {
                "seq": r[0], "node": r[1], "input_preview": r[2], "output_preview": r[3],
                "input_digest": r[4], "output_digest": r[5], "model": r[6],
                "tokens": r[7], "prev_sha256": r[8], "created_at": str(r[9]),
            }
            for r in rows
        ]
    except Exception:  # noqa: BLE001
        return []


def verify_chain(scan_id: int) -> dict:
    rows = list_artifacts(scan_id)
    prev = ""
    for r in rows:
        cur_prev = (r["prev_sha256"] or "").strip()
        if cur_prev != prev:
            return {"ok": False, "broken_at": r["seq"], "node": r["node"],
                    "expected": prev, "actual": cur_prev}
        prev = r["output_digest"]
    return {"ok": True, "count": len(rows), "head": prev}


def summarize_state(state: Any) -> dict:
    keys = (
        "repo_path", "license_declaration", "profile", "engine_findings", "evidence",
        "triaged_findings", "deploy", "deploy_status", "target_url", "poc_results", "phase",
    )
    return {k: state.get(k) for k in keys if k in state}
