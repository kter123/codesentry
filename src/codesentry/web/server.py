"""CodeSentry WebUI 服务（M5.1 骨架）：FastAPI + WS，托管 React 静态资源。"""

from __future__ import annotations

import ipaddress
import os
import shutil
import socket
import tarfile
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import (
    BackgroundTasks,
    FastAPI,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from codesentry.db.pool import get_conn

app = FastAPI(title="CodeSentry WebUI", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# M5.2 图审阅 API（graph/source/finding 详情）
# M5.3 管理面板 API
# M6.1 控制平面 API
# M6.1 认证中间件与 API（可开关）
from codesentry.web import (
    admin_api,  # noqa: F401
    auth_api,  # noqa: F401
    control_api,  # noqa: F401
    graph_api,  # noqa: F401
    projects_api,  # noqa: F401
)

WORK_ROOT = Path(os.environ.get("CODESENTRY_WORK_DIR", "work"))


def _work_root() -> Path:
    return Path(os.environ.get("CODESENTRY_WORK_DIR", "work"))
MAX_UPLOAD = 500 * 1024 * 1024
MAX_DIFF = 5 * 1024 * 1024
MAX_ENTRIES = 10_000
ALLOWED_ARCHIVE = (".zip", ".tar", ".tar.gz", ".tgz")


def _bad_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(
        (
            ip.is_private, ip.is_loopback, ip.is_link_local,
            ip.is_reserved, ip.is_unspecified, ip.is_multicast,
        )
    )


def _validate_git_url(git_url: str) -> str:
    parsed = urlparse(git_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        raise HTTPException(400, "git_url must be https")
    if host in {"localhost"} or host.endswith(".local"):
        raise HTTPException(400, "git host not allowed")
    try:
        ip = ipaddress.ip_address(host)
        if _bad_ip(ip):
            raise HTTPException(400, "git host not allowed")
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError as e:
            raise HTTPException(400, "git host resolve failed") from e
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except ValueError:
                continue
            if _bad_ip(ip):
                raise HTTPException(400, "git host resolves to private address")
    return git_url


def _safe_extract(archive_path: Path, kind: str, dest: Path) -> None:
    try:
        if kind == "zip":
            with zipfile.ZipFile(archive_path) as z:
                infos = z.infolist()
                if len(infos) > MAX_ENTRIES:
                    raise HTTPException(400, "archive has too many entries")
                if sum(i.file_size for i in infos) > MAX_UPLOAD * 3:
                    raise HTTPException(400, "archive expands too large")
                names = z.namelist()
                if any(n.startswith("/") or ".." in Path(n).parts for n in names):
                    raise HTTPException(400, "archive contains unsafe path")
                z.extractall(dest)
        else:
            with tarfile.open(archive_path) as t:
                members = t.getmembers()
                if len(members) > MAX_ENTRIES:
                    raise HTTPException(400, "archive has too many entries")
                if sum(m.size for m in members) > MAX_UPLOAD * 3:
                    raise HTTPException(400, "archive expands too large")
                for m in members:
                    if m.name.startswith("/") or ".." in Path(m.name).parts:
                        raise HTTPException(400, "archive contains unsafe path")
                    if m.issym() or m.islnk():
                        raise HTTPException(400, "archive links not allowed")
                try:
                    t.extractall(dest, filter="data")
                except TypeError:  # pragma: no cover - Python < 3.12
                    t.extractall(dest)
    except (zipfile.BadZipFile, tarfile.TarError) as e:
        raise HTTPException(400, f"bad archive: {e}") from e


class ScanOut(BaseModel):
    id: int
    repo_path: str
    OSS: bool
    status: str
    mode: str
    created: str | None = None


def _insert_scan(repo_path: str, oss: bool) -> int:
    from codesentry.control.snapshots import build_scan_snapshot, snapshot_json

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scans (repo_path, license_oss, license_declared_at, mode, status)"
            " VALUES (%s,%s,%s,'full','running') RETURNING id",
            (repo_path, oss, datetime.now(UTC)),
        )
        scan_id = int(cur.fetchone()[0])
        conn.commit()

    snapshot = build_scan_snapshot(scan_id)
    prompt_snap, skill_snap, llm_snap = snapshot_json(snapshot)
    profile_ids = [
        v.get("profile_id") for v in snapshot.get("llm_snapshot", {}).values() if v.get("profile_id")
    ]
    default_pid = int(profile_ids[0]) if profile_ids else None
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE scans SET prompt_snapshot=%s, skill_snapshot=%s, llm_snapshot=%s,"
            " llm_profile_id=%s, graph_snapshot=%s WHERE id=%s",
            (prompt_snap, skill_snap, llm_snap, default_pid,
             '{"template": "default", "version": 1}', scan_id),
        )
        conn.commit()
    return scan_id


def _run_scan_bg(scan_id: int, repo: str, oss: bool, out_dir: str) -> None:
    import threading

    t = threading.Thread(target=_scan_worker, args=(scan_id, repo, oss, out_dir), daemon=True)
    t.start()


def _notify(event: str, payload: dict) -> None:
    import threading

    def run() -> None:
        try:
            from codesentry.control.notifications import dispatch_all

            dispatch_all(event, payload)
        except Exception:  # noqa: BLE001, S110
            pass

    threading.Thread(target=run, daemon=True).start()


def _scan_worker(scan_id: int, repo: str, oss: bool, out_dir: str) -> None:
    from codesentry.orchestrator.runner import run_scan_graph

    try:
        code = run_scan_graph(repo=repo, OSS=oss, out_dir=out_dir, scan_id=scan_id)
        _broadcast(scan_id, {"event": "scan_done", "ok": code == 0, "scan_id": scan_id})
        _notify("scan.completed" if code == 0 else "scan.failed",
                {"scan_id": scan_id, "repo": repo, "ok": code == 0})
    except Exception as e:  # noqa: BLE001 - 后台线程异常必须回填失败状态
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE scans SET status='failed', error_reason=%s WHERE id=%s",
                    (str(e)[:500], scan_id),
                )
                conn.commit()
        except Exception:  # noqa: BLE001, S110
            pass
        _broadcast(scan_id, {"event": "scan_done", "ok": False, "scan_id": scan_id,
                             "error": str(e)[:200]})
        _notify("scan.failed", {"scan_id": scan_id, "repo": repo, "ok": False,
                                "error": str(e)[:200]})


class _Hub:
    def __init__(self) -> None:
        self.rooms: dict[int, set[WebSocket]] = {}

    async def join(self, scan_id: int, ws: WebSocket) -> None:
        await ws.accept()
        self.rooms.setdefault(scan_id, set()).add(ws)

    def leave(self, scan_id: int, ws: WebSocket) -> None:
        self.rooms.get(scan_id, set()).discard(ws)

    def broadcast(self, scan_id: int, payload: str) -> None:
        self._pending.setdefault(scan_id, []).append(payload)

    _pending: dict[int, list[str]]

    def __init_subclass__(cls) -> None:  # pragma: no cover
        raise TypeError


hub = _Hub()
hub._pending = {}


def _broadcast(scan_id: int, payload: dict) -> None:
    import json

    hub._pending.setdefault(scan_id, []).append(json.dumps(payload))


@app.on_event("startup")
async def _start_pump() -> None:
    import asyncio
    import json as _json

    async def pump() -> None:
        from codesentry.orchestrator.events import drain, room_ids

        while True:
            for sid, items in list(hub._pending.items()):
                cons = hub.rooms.get(sid, set())
                while items:
                    payload = items.pop(0)
                    for ws in list(cons):
                        try:
                            await ws.send_text(_json.dumps(payload) if isinstance(payload, dict) else payload)
                        except Exception:  # noqa: BLE001
                            hub.leave(sid, ws)
            for sid in room_ids():
                events = drain(sid)
                for event in events:
                    for ws in list(hub.rooms.get(sid, set())):
                        try:
                            await ws.send_text(_json.dumps(event, ensure_ascii=False))
                        except Exception:  # noqa: BLE001
                            hub.leave(sid, ws)
            await asyncio.sleep(0.5)

    asyncio.create_task(pump())
    try:
        from codesentry.config import get_settings

        settings = get_settings()
        if settings.scheduler_enabled:
            from codesentry.control.scheduler import start_scheduler

            start_scheduler(settings.scheduler_interval_s)
    except Exception:  # noqa: BLE001, S110
        pass


@app.websocket("/ws/scans/{scan_id}")
async def ws_scan(scan_id: int, ws: WebSocket) -> None:
    from codesentry.config import get_settings

    if get_settings().auth_enabled:
        from codesentry.control import auth

        user = auth.resolve_identity(
            ws.headers.get("authorization"), ws.cookies.get(auth.COOKIE_NAME)
        )
        if not user or not auth.role_ok(user, "viewer", "GET", f"/api/scans/{scan_id}"):
            await ws.accept()
            await ws.close(code=4401)
            return
    await hub.join(scan_id, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        hub.leave(scan_id, ws)


@app.post("/api/scans")
async def upload_scan(
    file: UploadFile | None = None,
    git_url: str = "",
    diff_text: str = Form(""),
    oss: bool = False,
    bg: BackgroundTasks = None,  # type: ignore[assignment]
):
    _work_root().mkdir(parents=True, exist_ok=True)
    job = uuid.uuid4().hex[:10]
    dest = _work_root() / job
    dest.mkdir(parents=True, exist_ok=True)

    if file is not None and file.filename:
        lower = file.filename.lower()
        if lower.endswith(".zip"):
            kind, ext = "zip", ".zip"
        elif lower.endswith((".tar", ".tar.gz", ".tgz")):
            kind, ext = "tar", (".tar.gz" if lower.endswith(".tar.gz") else Path(lower).suffix)
        else:
            raise HTTPException(400, "unsupported archive type")
        archive_path = dest / ("upload" + ext)
        total = 0
        with archive_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD:
                    out.close()
                    archive_path.unlink(missing_ok=True)
                    raise HTTPException(413, "upload too large")
                out.write(chunk)
        _safe_extract(archive_path, kind, dest / "src")
        repo = str(dest / "src")
    elif git_url:
        _validate_git_url(git_url)
        import subprocess

        try:
            r = await run_in_threadpool(
                subprocess.run,
                ["git", "clone", "--depth", "1", "--single-branch", "--no-tags",
                 git_url, str(dest / "src")],
                capture_output=True, text=True, timeout=120, check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise HTTPException(400, "clone timed out") from e
        if r.returncode != 0:
            raise HTTPException(400, "clone failed")
        repo = str(dest / "src")
    elif diff_text:
        if len(diff_text) > MAX_DIFF:
            raise HTTPException(413, "diff too large")
        (dest / "src").mkdir()
        (dest / "src" / "patch.diff").write_text(diff_text, encoding="utf-8")
        repo = str(dest / "src")
    else:
        raise HTTPException(400, "provide file / git_url / diff_text")

    try:
        scan_id = _insert_scan(repo, oss)
    except Exception as e:
        raise HTTPException(503, "scan 落库失败（DB 不可用？）") from e
    out_dir = str(dest / "codesentry-report")
    if bg is not None:
        bg.add_task(_run_scan_bg, scan_id, repo, oss, out_dir)
    else:
        _run_scan_bg(scan_id, repo, oss, out_dir)
    return {"scan_id": scan_id, "repo": repo, "out": out_dir}


@app.get("/api/scans")
async def list_scans() -> list[dict]:
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, repo_path, license_oss, status, mode, deploy_status, target_url"
                " FROM scans ORDER BY id DESC LIMIT 200"
            )
            cols = ["id", "repo_path", "OSS", "status", "mode", "deploy_status", "target_url"]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception:  # noqa: BLE001 - DB 不可用降级为空列表
        return []


@app.get("/api/scans/{scan_id}")
async def get_scan(scan_id: int) -> dict:
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, repo_path, license_oss, status, mode, deploy_status, deploy_log, target_url"
                " FROM scans WHERE id=%s",
                (scan_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404)
            cur.execute(
                "SELECT node, started_at, duration_ms, tokens, status, error FROM node_runs WHERE scan_id=%s ORDER BY started_at",
                (scan_id,),
            )
            node_rows = cur.fetchall()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(503, "scan 查询失败（DB 不可用？）") from e
    timeline = [
        {"node": n, "started": str(s), "duration_ms": d, "tokens": t, "status": st, "error": e}
        for n, s, d, t, st, e in node_rows
    ]
    keys = ["id", "repo_path", "OSS", "status", "mode", "deploy_status", "deploy_log", "target_url"]
    return dict(zip(keys, row)) | {"timeline": timeline}


@app.get("/api/scans/{scan_id}/sarif")
async def get_sarif(scan_id: int):
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT report_dir FROM scans WHERE id=%s", (scan_id,))
            row = cur.fetchone()
    except Exception as e:
        raise HTTPException(503, "scan 查询失败") from e
    if not row:
        raise HTTPException(404)
    report_dir = Path(str(row[0] or "")).resolve()
    if _work_root().resolve() not in report_dir.parents:
        raise HTTPException(404)
    path = report_dir / "report.sarif"
    if not path.is_file():
        raise HTTPException(404, "SARIF 尚未生成")
    return FileResponse(path, media_type="application/sarif+json", filename=f"scan-{scan_id}.sarif")


@app.post("/api/scans/{scan_id}/replay")
async def replay_scan(scan_id: int, bg: BackgroundTasks = None) -> dict:  # type: ignore[assignment]
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT repo_path, license_oss, prompt_snapshot, skill_snapshot, llm_snapshot"
                " FROM scans WHERE id=%s",
                (scan_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404)
            repo, oss, prompt_snap, skill_snap, llm_snap = row
            job = uuid.uuid4().hex[:10]
            out_dir = str(_work_root() / job / "codesentry-report")
            cur.execute(
                "INSERT INTO scans (repo_path, license_oss, license_declared_at, mode, status,"
                " prompt_snapshot, skill_snapshot, llm_snapshot, graph_snapshot, report_dir)"
                " VALUES (%s,%s,%s,'replay','running',%s,%s,%s,%s,%s) RETURNING id",
                (repo, oss, datetime.now(UTC), prompt_snap, skill_snap, llm_snap,
                 '{"template": "default", "version": 1}', out_dir),
            )
            new_id = int(cur.fetchone()[0])
            conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(503, "replay 创建失败") from e
    if bg is not None:
        bg.add_task(_run_scan_bg, new_id, str(repo), bool(oss), out_dir)
    else:
        _run_scan_bg(new_id, str(repo), bool(oss), out_dir)
    return {"ok": True, "scan_id": new_id, "replayed_from": scan_id}


# ---- Settings (API key 管理 R10) ----
SETTING_KEYS = {
    "model_base_url": "llm",
    "model_api_key": "llm",
    "fast_model": "llm",
    "deep_model": "llm",
    "embedding_base_url": "embedding",
    "embedding_model": "embedding",
    "embedding_api_key": "embedding",
    "codeql_bin": "codeql",
    "codeql_search_path": "codeql",
    "codeql_suite": "codeql",
    "codeql_build_mode": "codeql",
    "codeql_build_command": "codeql",
    "codeql_timeout_s": "codeql",
    "codeql_db_cache": "codeql",
    "codeql_auto_install": "codeql",
    "codeql_version": "codeql",
    "codeql_license_ack": "codeql",
    "codeql_install_dir": "codeql",
    "codeql_sha256": "codeql",
    "smtp_host": "notifications",
    "smtp_port": "notifications",
    "smtp_user": "notifications",
    "smtp_password": "notifications",
    "smtp_from": "notifications",
    "smtp_to": "notifications",
    "smtp_tls": "notifications",
    "poc_remote_enabled": "poc",
    "poc_remote_allow_private": "poc",
}


def _sensitive_setting(key: str) -> bool:
    return key.endswith(("api_key", "password", "secret"))


def _mask(key: str, val: str) -> str:
    return (val[:8] + "…") if _sensitive_setting(key) and len(val) > 8 else val


@app.get("/api/settings/{group}")
async def get_settings_group(group: str) -> dict:
    if group not in ("llm", "embedding", "codeql", "notifications", "poc"):
        raise HTTPException(404)
    out: dict[str, str] = {}
    for key, g in SETTING_KEYS.items():
        if group == "llm" and g != "llm":
            continue
        if group == "embedding" and g != "embedding":
            continue
        if group == "notifications" and g != "notifications":
            continue
        if group == "codeql" and g != "codeql":
            continue
        if group == "poc" and g != "poc":
            continue
        val = _read_setting(key)
        out[key] = _mask(key, val)
    return out


def _read_setting(key: str) -> str:
    from codesentry.config import get_settings
    from codesentry.security.secrets import SecretError, decrypt_secret

    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT value FROM app_settings WHERE key=%s", (key,))
            row = cur.fetchone()
        if row is not None:
            val = str(row[0])
            if _sensitive_setting(key) and val:
                try:
                    return decrypt_secret(val)
                except SecretError:
                    return ""
            return val
    except Exception:  # noqa: BLE001, S110
        pass
    s = get_settings()
    return {
        "model_base_url": s.model_base_url,
        "model_api_key": s.model_api_key,
        "fast_model": s.fast_model,
        "deep_model": s.deep_model,
        "embedding_base_url": s.embedding_base_url,
        "embedding_model": s.embedding_model,
        "embedding_api_key": s.embedding_api_key,
        "codeql_bin": s.codeql_bin,
        "codeql_search_path": s.codeql_search_path,
        "codeql_suite": s.codeql_suite,
        "codeql_build_mode": s.codeql_build_mode,
        "codeql_build_command": s.codeql_build_command,
        "codeql_timeout_s": str(s.codeql_timeout_s),
        "codeql_db_cache": str(s.codeql_db_cache).lower(),
        "codeql_auto_install": str(s.codeql_auto_install).lower(),
        "codeql_version": s.codeql_version,
        "codeql_license_ack": str(s.codeql_license_ack).lower(),
        "codeql_install_dir": s.codeql_install_dir,
        "codeql_sha256": s.codeql_sha256,
        "smtp_host": os.environ.get("CODESENTRY_SMTP_HOST", ""),
        "smtp_port": os.environ.get("CODESENTRY_SMTP_PORT", "587"),
        "smtp_user": os.environ.get("CODESENTRY_SMTP_USER", ""),
        "smtp_password": os.environ.get("CODESENTRY_SMTP_PASSWORD", ""),
        "smtp_from": os.environ.get("CODESENTRY_SMTP_FROM", ""),
        "smtp_to": os.environ.get("CODESENTRY_SMTP_TO", ""),
        "smtp_tls": os.environ.get("CODESENTRY_SMTP_TLS", "true"),
        "poc_remote_enabled": str(s.poc_remote_enabled).lower(),
        "poc_remote_allow_private": str(s.poc_remote_allow_private).lower(),
    }.get(key, "")


class SettingsPayload(BaseModel):
    values: dict[str, str]


@app.put("/api/settings/{group}")
async def put_settings_group(group: str, payload: SettingsPayload) -> dict:
    if group not in ("llm", "embedding", "codeql", "notifications", "poc"):
        raise HTTPException(404)
    for k, v in payload.values.items():
        if k not in SETTING_KEYS or SETTING_KEYS[k] != group:
            raise HTTPException(400, f"unknown key {k}")
        stored = v
        if _sensitive_setting(k) and v:
            from codesentry.security.secrets import encrypt_secret

            stored = encrypt_secret(v)
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO app_settings (key, value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=%s, updated_at=now()",
                    (k, stored, stored),
                )
                conn.commit()
        except Exception as e:
            raise HTTPException(503, f"settings 写库失败：{e}") from e
    return {"ok": True, "keys": list(payload.values)}


@app.post("/api/settings/{group}/test")
async def test_settings_group(group: str) -> dict:
    try:
        if group == "llm":
            import openai

            from codesentry.config import get_settings as gs

            cfg = gs()
            c = openai.OpenAI(base_url=cfg.model_base_url, api_key=cfg.model_api_key, timeout=15)
            r = c.chat.completions.create(
                model=cfg.fast_model,
                messages=[{"role": "user", "content": "1"}],
                max_tokens=1,
                temperature=0,
            )
            return {"ok": True, "reply_len": len(r.choices[0].message.content or "")}
        if group == "notifications":
            from codesentry.control.notifications import test_email

            return test_email()
        if group == "codeql":
            return {"ok": False, "error": "CodeQL 使用 /api/engines/codeql/test"}
        from codesentry.rag.embedding import EmbeddingClient

        ec = EmbeddingClient.from_config()
        v = ec.embed(["t"])
        return {"ok": True, "dims": len(v[0])}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


@app.delete("/api/scans/{scan_id}")
async def delete_scan(scan_id: int) -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT repo_path FROM scans WHERE id=%s", (scan_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404)
    repo = Path(row[0])
    # 只清理 work/ 内目录（防路径穿越）
    resolved = repo.resolve()
    if _work_root().resolve() in resolved.parents:
        shutil.rmtree(resolved, ignore_errors=True)
    with get_conn() as conn, conn.cursor() as cur:
        # 阻止后台 worker 在删除过程中继续插入子表，避免 FK 竞态
        cur.execute("SET LOCAL lock_timeout = '5s'")
        cur.execute("LOCK TABLE node_runs, findings, budget_ledger IN ACCESS EXCLUSIVE MODE")
        cur.execute("DELETE FROM findings WHERE scan_id=%s", (scan_id,))
        cur.execute("DELETE FROM node_runs WHERE scan_id=%s", (scan_id,))
        cur.execute("DELETE FROM budget_ledger WHERE scan_id=%s", (scan_id,))
        cur.execute("DELETE FROM llm_usage WHERE scan_id=%s", (scan_id,))
        cur.execute("DELETE FROM scans WHERE id=%s", (scan_id,))
        conn.commit()
    try:
        from codesentry.sandbox.deploy import cleanup_scan

        cleanup_scan(scan_id)
    except Exception:  # noqa: BLE001, S110
        pass
    return {"ok": True}


@app.get("/")
async def root() -> dict:
    return {"service": "codesentry-webui", "ui": "/ui", "docs": "/docs"}


def cleanup_mtime_cache() -> None:  # pragma: no cover
    shutil.rmtree(_work_root() / ".tmp", ignore_errors=True)


# 静态托管（M5.2 起接入前端 build；骨架期占位）
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    _STATIC_ROOT = STATIC_DIR.resolve()
    _assets = STATIC_DIR / "assets"
    if _assets.is_dir():
        # 必须先挂载，再注册 catch-all；否则 /assets/* 会被 catch-all 截获
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")
    _SPA_SEGMENTS = {
        "agents", "rules", "skills", "prompts", "reviews", "scans", "review",
        "llm", "usage", "orchestration", "audit", "settings", "users", "login",
        "projects",
    }

    @app.get("/{spa_path:path}")
    async def root_fallback(spa_path: str):
        if "\x00" in spa_path:
            raise HTTPException(404)
        first = spa_path.split("/")[0] if spa_path else ""
        if spa_path == "" or first in _SPA_SEGMENTS or first == "ui":  # /agents... 与 /ui/... 都直接回 index
            if spa_path.startswith("ui/"):
                rel = spa_path[len("ui/"):]
                candidate = (STATIC_DIR / rel).resolve()
                try:
                    candidate.relative_to(_STATIC_ROOT)
                except ValueError as e:
                    raise HTTPException(404) from e
                if candidate.is_file():
                    return FileResponse(candidate)
            return FileResponse(STATIC_DIR / "index.html")
        raise HTTPException(404)
