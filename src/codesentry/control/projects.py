"""项目与定时扫描（P1）：cron 计算、项目/计划 CRUD、路径校验。"""

from __future__ import annotations

import ipaddress
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse


def _parse_field(expr: str, lo: int, hi: int) -> set[int]:
    values: set[int] = set()
    for part in str(expr).split(","):
        part = part.strip()
        if not part:
            raise ValueError("cron 字段为空")
        step = 1
        if "/" in part:
            part, step_raw = part.split("/", 1)
            step = int(step_raw)
            if step <= 0:
                raise ValueError("cron step 必须 > 0")
        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        if start < lo or end > hi or start > end:
            raise ValueError(f"cron 值越界：{part}（{lo}-{hi}）")
        values.update(range(start, end + 1, step))
    return values


def parse_cron(cron: str) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
    fields = str(cron or "").split()
    if len(fields) != 5:
        raise ValueError("cron 必须是 5 段：分 时 日 月 周")
    minute = _parse_field(fields[0], 0, 59)
    hour = _parse_field(fields[1], 0, 23)
    dom = _parse_field(fields[2], 1, 31)
    month = _parse_field(fields[3], 1, 12)
    dow = {0 if v == 7 else v for v in _parse_field(fields[4], 0, 7)}
    return minute, hour, dom, month, dow


def cron_next(cron: str, after: datetime | None = None) -> datetime:
    minute, hour, dom, month, dow = parse_cron(cron)
    now = after or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    current = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
    dom_restricted = str(cron).split()[2] != "*"
    dow_restricted = str(cron).split()[4] != "*"
    for _ in range(366 * 24 * 60):
        weekday = (current.weekday() + 1) % 7  # cron: Sunday=0
        if dom_restricted and dow_restricted:
            day_ok = (current.day in dom) or (weekday in dow)
        elif dom_restricted:
            day_ok = current.day in dom
        elif dow_restricted:
            day_ok = weekday in dow
        else:
            day_ok = True
        if (current.month in month and day_ok
                and current.hour in hour and current.minute in minute):
            return current
        current += timedelta(minutes=1)
    raise ValueError("cron 在一年内没有匹配时间")


def _work_root() -> Path:
    import os

    return Path(os.environ.get("CODESENTRY_WORK_DIR", "work")).resolve()


def validate_repo_path(repo_path: str) -> str:
    if not repo_path:
        return ""
    path = Path(repo_path).resolve()
    root = _work_root()
    if path != root and root not in path.parents:
        raise ValueError("repo_path 必须位于 work 根目录内")
    if not path.is_dir():
        raise ValueError("repo_path 不存在或不是目录")
    return str(path)


def validate_git_url(git_url: str) -> str:
    if not git_url:
        return ""
    parsed = urlparse(git_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        raise ValueError("git_url 必须是 https")
    if host == "localhost" or host.endswith(".local"):
        raise ValueError("git host 不允许本地域名")
    try:
        ip = ipaddress.ip_address(host)
        if _bad_ip(ip):
            raise ValueError("git host 不允许私网地址")
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError as e:
            raise ValueError("git host 解析失败") from e
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except ValueError:
                continue
            if _bad_ip(ip):
                raise ValueError("git host 解析到私网地址")
    return git_url


def _bad_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any((ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_reserved,
                ip.is_unspecified, ip.is_multicast))


def list_projects() -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, repo_path, git_url, oss, enabled, created_at, updated_at"
                " FROM projects ORDER BY id"
            )
            rows = cur.fetchall()
        cols = ["id", "name", "repo_path", "git_url", "oss", "enabled",
                "created_at", "updated_at"]
        return [{**dict(zip(cols, r)), "created_at": str(r[6]),
                 "updated_at": str(r[7])} for r in rows]
    except Exception:  # noqa: BLE001
        return []


def get_project(project_id: int) -> dict | None:
    return next((p for p in list_projects() if int(p["id"]) == int(project_id)), None)


def create_project(name: str, *, repo_path: str = "", git_url: str = "",
                   oss: bool = False, enabled: bool = True) -> dict:
    if not str(name).strip():
        raise ValueError("项目名称必填")
    repo_path = validate_repo_path(repo_path)
    git_url = validate_git_url(git_url)
    if not repo_path and not git_url:
        raise ValueError("repo_path 与 git_url 至少提供一个")
    from codesentry.control.audit import audit_write
    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.db.pool import get_conn

    ensure_control_schema()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO projects (name, repo_path, git_url, oss, enabled)"
            " VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (name.strip(), repo_path, git_url, bool(oss), bool(enabled)),
        )
        pid = int(cur.fetchone()[0])
        conn.commit()
    audit_write("api", "create", "project", str(pid), None,
                {"name": name, "repo_path": repo_path, "git_url": git_url})
    return get_project(pid) or {"id": pid}


def update_project(project_id: int, patch: dict) -> dict | None:
    current = get_project(project_id)
    if not current:
        return None
    repo_path = patch.get("repo_path", current["repo_path"])
    git_url = patch.get("git_url", current["git_url"])
    repo_path = validate_repo_path(repo_path)
    git_url = validate_git_url(git_url)
    if not repo_path and not git_url:
        raise ValueError("repo_path 与 git_url 至少提供一个")
    from codesentry.control.audit import audit_write
    from codesentry.db.pool import get_conn

    fields = {
        "name": patch.get("name", current["name"]),
        "repo_path": repo_path, "git_url": git_url,
        "oss": bool(patch.get("oss", current["oss"])),
        "enabled": bool(patch.get("enabled", current["enabled"])),
    }
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE projects SET name=%s, repo_path=%s, git_url=%s, oss=%s, enabled=%s,"
            " updated_at=now() WHERE id=%s",
            (fields["name"], fields["repo_path"], fields["git_url"], fields["oss"],
             fields["enabled"], int(project_id)),
        )
        conn.commit()
    audit_write("api", "update", "project", str(project_id), current, fields)
    return get_project(project_id)


def delete_project(project_id: int) -> bool:
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM projects WHERE id=%s", (int(project_id),))
        ok = cur.rowcount > 0
        conn.commit()
    return ok


def list_schedules() -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT s.id, s.project_id, p.name, s.name, s.cron, s.enabled,"
                " s.last_run_at, s.next_run_at, s.last_scan_id, s.last_error, s.created_at,"
                " p.repo_path, p.git_url, p.oss"
                " FROM scan_schedules s LEFT JOIN projects p ON p.id=s.project_id"
                " ORDER BY s.id"
            )
            rows = cur.fetchall()
        cols = ["id", "project_id", "project_name", "name", "cron", "enabled",
                "last_run_at", "next_run_at", "last_scan_id", "last_error", "created_at",
                "repo_path", "git_url", "oss"]
        return [{**dict(zip(cols, r)), "last_run_at": str(r[6]) if r[6] else None,
                 "next_run_at": str(r[7]) if r[7] else None,
                 "created_at": str(r[10])} for r in rows]
    except Exception:  # noqa: BLE001
        return []


def create_schedule(project_id: int, *, name: str = "", cron: str = "0 3 * * *",
                    enabled: bool = True) -> dict:
    if get_project(project_id) is None:
        raise ValueError("项目不存在")
    next_run = cron_next(cron)
    from codesentry.control.audit import audit_write
    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.db.pool import get_conn

    ensure_control_schema()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scan_schedules (project_id, name, cron, enabled, next_run_at)"
            " VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (int(project_id), name, cron, bool(enabled), next_run),
        )
        sid = int(cur.fetchone()[0])
        conn.commit()
    audit_write("api", "create", "scan_schedule", str(sid), None,
                {"project_id": project_id, "cron": cron})
    return next(s for s in list_schedules() if int(s["id"]) == sid)


def update_schedule(schedule_id: int, patch: dict) -> dict | None:
    current = next((s for s in list_schedules() if int(s["id"]) == int(schedule_id)), None)
    if not current:
        return None
    cron = patch.get("cron", current["cron"])
    next_run = cron_next(cron) if cron != current["cron"] else current["next_run_at"]
    from codesentry.control.audit import audit_write
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE scan_schedules SET name=%s, cron=%s, enabled=%s, next_run_at=%s,"
            " updated_at=now() WHERE id=%s",
            (patch.get("name", current["name"]), cron,
             bool(patch.get("enabled", current["enabled"])),
             next_run, int(schedule_id)),
        )
        conn.commit()
    audit_write("api", "update", "scan_schedule", str(schedule_id), current, patch)
    return next((s for s in list_schedules() if int(s["id"]) == int(schedule_id)), None)


def delete_schedule(schedule_id: int) -> bool:
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM scan_schedules WHERE id=%s", (int(schedule_id),))
        ok = cur.rowcount > 0
        conn.commit()
    return ok


def claim_due_schedules(now: datetime | None = None, limit: int = 10) -> list[dict]:
    now = now or datetime.now(UTC)
    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.db.pool import get_conn

    ensure_control_schema()
    out: list[dict] = []
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT s.id, s.project_id, p.name, p.repo_path, p.git_url, p.oss, s.cron"
            " FROM scan_schedules s JOIN projects p ON p.id=s.project_id"
            " WHERE s.enabled AND p.enabled AND s.next_run_at IS NOT NULL"
            " AND s.next_run_at <= %s"
            " ORDER BY s.next_run_at LIMIT %s FOR UPDATE OF s SKIP LOCKED",
            (now, max(1, min(int(limit), 50))),
        )
        rows = cur.fetchall()
        for row in rows:
            try:
                nxt = cron_next(str(row[6]), now)
            except ValueError:
                nxt = None
                cur.execute(
                    "UPDATE scan_schedules SET enabled=FALSE, last_error=%s, updated_at=now()"
                    " WHERE id=%s",
                    ("cron 无法计算下一次时间", int(row[0])),
                )
                continue
            cur.execute(
                "UPDATE scan_schedules SET last_run_at=%s, next_run_at=%s, updated_at=now()"
                " WHERE id=%s",
                (now, nxt, int(row[0])),
            )
            out.append({"id": int(row[0]), "project_id": int(row[1]), "name": row[2],
                        "repo_path": row[3] or "", "git_url": row[4] or "",
                        "oss": bool(row[5]), "cron": row[6], "next_run_at": nxt})
        conn.commit()
    return out


def mark_schedule_result(schedule_id: int, scan_id: int | None, error: str = "") -> None:
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE scan_schedules SET last_scan_id=%s, last_error=%s, updated_at=now()"
            " WHERE id=%s",
            (scan_id, error[:500], int(schedule_id)),
        )
        conn.commit()
