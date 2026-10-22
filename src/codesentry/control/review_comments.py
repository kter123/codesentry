"""审查协作（M6.7/FR-44）：扫描/Finding 评论线程。"""

from __future__ import annotations


def add_comment(scan_id: int, body: str, *, finding_id: int | None = None,
                author: str = "") -> dict | None:
    if not body.strip():
        raise ValueError("评论不能为空")
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO review_comments (scan_id, finding_id, author, body)"
                " VALUES (%s,%s,%s,%s) RETURNING id, created_at",
                (int(scan_id), finding_id, author, body[:4000]),
            )
            cid, created = cur.fetchone()
            conn.commit()
        return {"id": int(cid), "scan_id": scan_id, "finding_id": finding_id,
                "author": author, "body": body[:4000], "created_at": str(created)}
    except Exception:  # noqa: BLE001
        return None


def list_comments(scan_id: int, finding_id: int | None = None) -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        clause = " AND finding_id=%s" if finding_id is not None else ""
        params: list = [int(scan_id)]
        if finding_id is not None:
            params.append(int(finding_id))
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, finding_id, author, body, created_at FROM review_comments"
                f" WHERE scan_id=%s{clause} ORDER BY id",
                params,
            )
            rows = cur.fetchall()
        return [{"id": r[0], "finding_id": r[1], "author": r[2], "body": r[3],
                 "created_at": str(r[4])} for r in rows]
    except Exception:  # noqa: BLE001
        return []
