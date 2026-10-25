"""后台定时扫描调度器（P1）：每 N 秒原子认领 due schedule。"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

_started = False
_lock = threading.Lock()


def _work_root() -> Path:
    import os

    return Path(os.environ.get("CODESENTRY_WORK_DIR", "work"))


def _clone(git_url: str, dest: Path) -> str:
    from codesentry.control.projects import validate_git_url

    validate_git_url(git_url)
    dest.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["git", "clone", "--depth", "1", "--single-branch", "--no-tags",
         git_url, str(dest / "src")],
        capture_output=True, text=True, timeout=120, check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"git clone failed: {r.stderr[-300:]}")
    return str(dest / "src")


def run_schedule(schedule: dict) -> int:
    """立即运行一个已认领 schedule，返回 scan_id。"""
    from codesentry.control.projects import mark_schedule_result, validate_repo_path
    from codesentry.web.server import _insert_scan, _run_scan_bg

    job = uuid.uuid4().hex[:10]
    dest = _work_root() / job
    dest.mkdir(parents=True, exist_ok=True)
    repo = ""
    try:
        if schedule.get("repo_path"):
            repo = validate_repo_path(str(schedule["repo_path"]))
        elif schedule.get("git_url"):
            repo = _clone(str(schedule["git_url"]), dest)
        else:
            raise ValueError("项目没有 repo_path/git_url")
        scan_id = _insert_scan(repo, bool(schedule.get("oss")))
        out_dir = str(dest / "codesentry-report")
        _run_scan_bg(scan_id, repo, bool(schedule.get("oss")), out_dir)
        mark_schedule_result(int(schedule["id"]), scan_id)
        return scan_id
    except Exception as e:
        mark_schedule_result(int(schedule["id"]), None, str(e))
        shutil.rmtree(dest, ignore_errors=True)
        raise


def _loop(interval_s: int) -> None:
    from datetime import UTC, datetime

    from codesentry.control.projects import claim_due_schedules

    while True:
        try:
            for item in claim_due_schedules(datetime.now(UTC)):
                try:
                    run_schedule(item)
                except Exception:  # noqa: BLE001, S110 - 单计划失败不终止调度器
                    pass
        except Exception:  # noqa: BLE001, S110
            pass
        time.sleep(max(5, int(interval_s)))


def start_scheduler(interval_s: int = 30) -> bool:
    global _started
    with _lock:
        if _started:
            return False
        _started = True
    thread = threading.Thread(target=_loop, args=(interval_s,), daemon=True,
                              name="codesentry-scheduler")
    thread.start()
    return True
