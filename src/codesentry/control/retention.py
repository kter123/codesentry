"""数据生命周期（M6.7/FR-39）：按天数清理扫描、容器与工作区。"""

from __future__ import annotations

import shutil
from pathlib import Path


def purge_scans(days: int) -> int:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn
        from codesentry.sandbox.deploy import cleanup_scan

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM scans WHERE created_at < now() - make_interval(days => %s)",
                (max(1, int(days)),),
            )
            ids = [int(r[0]) for r in cur.fetchall()]
        for sid in ids:
            cleanup_scan(sid)
            try:
                from codesentry.config import get_settings

                shutil.rmtree(Path(get_settings().work_dir) / "deploy" / str(sid), ignore_errors=True)
            except Exception:  # noqa: BLE001, S110
                pass
        with get_conn() as conn, conn.cursor() as cur:
            for sid in ids:
                for table in ("agent_artifacts", "review_comments", "findings",
                              "node_runs", "budget_ledger", "llm_usage"):
                    cur.execute(f"DELETE FROM {table} WHERE scan_id=%s", (sid,))
                cur.execute("DELETE FROM scans WHERE id=%s", (sid,))
            conn.commit()
        return len(ids)
    except Exception:  # noqa: BLE001
        return 0


def disk_usage() -> dict:
    try:
        from codesentry.config import get_settings

        root = Path(get_settings().work_dir)
        total = 0
        entries = 0
        if root.exists():
            for p in root.rglob("*"):
                if p.is_file():
                    try:
                        total += p.stat().st_size
                        entries += 1
                    except OSError:
                        continue
        return {"work_dir": str(root), "bytes": total, "mb": round(total / 1024 / 1024, 2),
                "files": entries}
    except Exception:  # noqa: BLE001
        return {"work_dir": "", "bytes": 0, "mb": 0.0, "files": 0}
