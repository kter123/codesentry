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
                "SELECT id, repo_path FROM scans WHERE created_at < now() - make_interval(days => %s)",
                (max(1, int(days)),),
            )
            rows = cur.fetchall()
            ids = [int(r[0]) for r in rows]
            repos = {int(r[0]): str(r[1] or "") for r in rows}
        for sid in ids:
            cleanup_scan(sid)
            try:
                from codesentry.config import get_settings

                root = Path(get_settings().work_dir).resolve()
                shutil.rmtree(root / "deploy" / str(sid), ignore_errors=True)
                repo = Path(repos.get(sid, "")).resolve() if repos.get(sid) else None
                if repo and root in repo.parents:
                    rel = repo.relative_to(root)
                    if rel.parts:
                        job = root / rel.parts[0]
                        with get_conn() as conn, conn.cursor() as cur:
                            cur.execute(
                                "SELECT count(*) FROM scans WHERE id <> %s"
                                " AND (repo_path = %s OR repo_path LIKE %s)",
                                (sid, str(repo), str(job) + "/%"),
                            )
                            shared = int(cur.fetchone()[0] or 0)
                        if not shared:
                            shutil.rmtree(job, ignore_errors=True)
            except Exception:  # noqa: BLE001, S110
                pass
        with get_conn() as conn, conn.cursor() as cur:
            for sid in ids:
                for table in ("audit_paths", "audit_rounds", "agent_artifacts",
                              "review_comments", "findings", "node_runs",
                              "budget_ledger", "llm_usage"):
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


def cleanup_codeql_cache(days: int = 7) -> int:
    """删除 work_dir/codeql-db 下超过 days 的数据库目录。"""
    import time

    from codesentry.config import get_settings

    root = Path(get_settings().work_dir) / "codeql-db"
    if not root.is_dir():
        return 0
    cutoff = time.time() - max(1, int(days)) * 86400
    removed = 0
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            if child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def cleanup_orphan_workdirs(days: int = 7, *, work_root: str | Path | None = None) -> int:
    """删除 work 根下未被任何 scans.repo_path 引用的过期 job 目录。"""
    import time

    from codesentry.config import get_settings
    from codesentry.db.pool import get_conn

    root = Path(work_root or get_settings().work_dir).resolve()
    if not root.is_dir():
        return 0
    referenced: set[Path] = set()
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT repo_path FROM scans WHERE repo_path <> ''")
            for (repo,) in cur.fetchall():
                p = Path(str(repo)).resolve()
                try:
                    rel = p.relative_to(root)
                except ValueError:
                    continue
                if rel.parts:
                    referenced.add(root / rel.parts[0])
    except Exception:  # noqa: BLE001
        return 0
    cutoff = time.time() - max(1, int(days)) * 86400
    removed = 0
    for child in root.iterdir():
        if not child.is_dir() or child.name in ("codeql-db", "deploy"):
            continue
        if child.resolve() in referenced:
            continue
        try:
            if child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def cleanup_target_images() -> int:
    """删除无容器引用的 codesentry-target-* 镜像。"""
    try:
        import docker

        client = docker.from_env(timeout=30)
        in_use = {c.image.id for c in client.containers.list(all=True)}
        removed = 0
        for image in client.images.list():
            tags = image.tags or []
            if not any(t.startswith("codesentry-target-") for t in tags):
                continue
            if image.id in in_use:
                continue
            try:
                client.images.remove(image.id, force=False)
                removed += 1
            except Exception:  # noqa: BLE001, S112
                continue
        client.close()
        return removed
    except Exception:  # noqa: BLE001
        return 0


def run_maintenance(*, days: int = 30, codeql_days: int = 7,
                    orphan_days: int = 7, clean_images: bool = False) -> dict:
    return {
        "scans": purge_scans(days),
        "codeql_cache": cleanup_codeql_cache(codeql_days),
        "orphan_workdirs": cleanup_orphan_workdirs(orphan_days),
        "target_images": cleanup_target_images() if clean_images else 0,
        "disk": disk_usage(),
    }
