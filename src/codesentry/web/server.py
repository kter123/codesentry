"""CodeSentry WebUI 服务（M5.1 骨架）：FastAPI + WS，托管 React 静态资源。"""

from __future__ import annotations

import os
import shutil
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
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
from codesentry.web import graph_api  # noqa: E402,F401

WORK_ROOT = Path(os.environ.get("CODESENTRY_WORK_DIR", "work"))


def _work_root() -> Path:
    return Path(os.environ.get("CODESENTRY_WORK_DIR", "work"))
MAX_UPLOAD = 500 * 1024 * 1024
ALLOWED_ZIP = {".zip", ".tar", ".gz", ".tgz"}


class ScanOut(BaseModel):
    id: int
    repo_path: str
    OSS: bool
    status: str
    mode: str
    created: str | None = None


def _insert_scan(repo_path: str, oss: bool) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scans (repo_path, license_oss, license_declared_at, mode, status) VALUES (%s,%s,%s,'full','running') RETURNING id",
            (repo_path, oss, datetime.now(UTC)),
        )
        scan_id = cur.fetchone()[0]
        conn.commit()
    return scan_id


def _run_scan_bg(scan_id: int, repo: str, oss: bool, out_dir: str) -> None:
    import threading

    t = threading.Thread(target=_scan_worker, args=(scan_id, repo, oss, out_dir), daemon=True)
    t.start()


def _scan_worker(scan_id: int, repo: str, oss: bool, out_dir: str) -> None:
    from codesentry.orchestrator.runner import run_scan_graph

    code = run_scan_graph(repo=repo, OSS=oss, out_dir=out_dir)
    _broadcast(scan_id, {"event": "scan_done", "ok": code == 0, "scan_id": scan_id})


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
        while True:
            for sid, items in list(hub._pending.items()):
                cons = hub.rooms.get(sid, set())
                while items:
                    payload = items.pop(0)
                    for ws in list(cons):
                        try:
                            await ws.send_text(_json.dumps(payload) if isinstance(payload, dict) else payload)
                        except Exception:  # noqa: BLE001, S110
                            hub.leave(sid, ws)
            await asyncio.sleep(0.5)

    asyncio.create_task(pump())


@app.websocket("/ws/scans/{scan_id}")
async def ws_scan(scan_id: int, ws: WebSocket) -> None:
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
    bg: BackgroundTasks = None,
):
    _work_root().mkdir(parents=True, exist_ok=True)
    job = uuid.uuid4().hex[:10]
    dest = _work_root() / job
    dest.mkdir(parents=True, exist_ok=True)

    if file is not None and file.filename:
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_ZIP:
            raise HTTPException(400, f"unsupported archive type {ext}")
        data = await file.read()
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "upload too large")
        archive_path = dest / file.filename
        archive_path.write_bytes(data)
        if ext == ".zip":
            try:
                with zipfile.ZipFile(archive_path) as z:
                    names = z.namelist()
                    if any(n.startswith("/") or ".." in n for n in names):
                        raise HTTPException(400, "zip contains unsafe path")
                    z.extractall(dest / "src")
            except zipfile.BadZipFile as e:
                raise HTTPException(400, f"bad zip: {e}") from e
        repo = str(dest / "src")
    elif git_url:
        if not git_url.startswith("https://"):
            raise HTTPException(400, "git_url must be https")
        import subprocess

        r = subprocess.run(
            ["git", "clone", "--depth", "1", git_url, str(dest / "src")],
            capture_output=True, text=True, timeout=600,
        )
        if r.returncode != 0:
            raise HTTPException(400, f"clone failed: {r.stderr[:200]}")
        repo = str(dest / "src")
    elif diff_text:
        (dest / "src").mkdir()
        (dest / "src" / "patch.diff").write_text(diff_text, encoding="utf-8")
        repo = str(dest / "src")
    else:
        raise HTTPException(400, "provide file / git_url / diff_text")

    scan_id = _insert_scan(repo, oss)
    out_dir = str(dest / "codesentry-report")
    bg.add_task(_run_scan_bg, scan_id, repo, oss, out_dir)
    return {"scan_id": scan_id, "repo": repo, "out": out_dir}


@app.get("/api/scans")
async def list_scans() -> list[dict]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, repo_path, license_oss, status, mode FROM scans ORDER BY id DESC LIMIT 200")
        cols = ["id", "repo_path", "OSS", "status", "mode"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


@app.get("/api/scans/{scan_id}")
async def get_scan(scan_id: int) -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, repo_path, license_oss, status, mode FROM scans WHERE id=%s", (scan_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404)
        cur.execute(
            "SELECT node, started_at, duration_ms, tokens, status, error FROM node_runs WHERE scan_id=%s ORDER BY started_at",
            (scan_id,),
        )
        timeline = [
            {"node": n, "started": str(s), "duration_ms": d, "tokens": t, "status": st, "error": e}
            for n, s, d, t, st, e in cur.fetchall()
        ]
        return dict(zip(["id", "repo_path", "OSS", "status", "mode"], row)) | {"timeline": timeline}


# 静态托管（M5.2 起接入 React build；骨架期占位）
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")


# ---- Settings (API key 管理 R10) ----
SETTING_KEYS = {
    "model_base_url": "llm",
    "model_api_key": "llm",
    "fast_model": "llm",
    "deep_model": "llm",
    "embedding_base_url": "embedding",
    "embedding_model": "embedding",
    "embedding_api_key": "embedding",
}


def _mask(key: str, val: str) -> str:
    return (val[:8] + "…") if key.endswith("api_key") and len(val) > 8 else val


@app.get("/api/settings/{group}")
async def get_settings_group(group: str) -> dict:
    if group not in ("llm", "embedding"):
        raise HTTPException(404)
    out: dict[str, str] = {}
    for key, g in SETTING_KEYS.items():
        if group == "llm" and g == "embedding":
            continue
        if group == "embedding" and g != "embedding":
            continue
        val = _read_setting(key)
        out[key] = _mask(key, val)
    return out


def _read_setting(key: str) -> str:
    from codesentry.config import get_settings

    s = get_settings()
    return {
        "model_base_url": s.model_base_url,
        "model_api_key": s.model_api_key,
        "fast_model": s.fast_model,
        "deep_model": s.deep_model,
        "embedding_base_url": s.embedding_base_url,
        "embedding_model": s.embedding_model,
        "embedding_api_key": s.embedding_api_key,
    }.get(key, "")


class SettingsPayload(BaseModel):
    values: dict[str, str]


@app.put("/api/settings/{group}")
async def put_settings_group(group: str, payload: SettingsPayload) -> dict:
    if group not in ("llm", "embedding"):
        raise HTTPException(404)
    for k, v in payload.values.items():
        if k not in SETTING_KEYS or SETTING_KEYS[k] != group:
            raise HTTPException(400, f"unknown key {k}")
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO app_settings (key, value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=%s, updated_at=now()",
                    (k, v, v),
                )
                conn.commit()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"settings 写库失败：{e}") from e
    return {"ok": True, "keys": list(payload.values)}


@app.post("/api/settings/{group}/test")
async def test_settings_group(group: str) -> dict:
    try:
        if group == "llm":
            import openai

            s = type("S", (), {})()
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
        cur.execute("DELETE FROM findings WHERE scan_id=%s", (scan_id,))
        cur.execute("DELETE FROM node_runs WHERE scan_id=%s", (scan_id,))
        cur.execute("DELETE FROM budget_ledger WHERE scan_id=%s", (scan_id,))
        cur.execute("DELETE FROM scans WHERE id=%s", (scan_id,))
        conn.commit()
    return {"ok": True}


@app.get("/")
async def root() -> dict:
    return {"service": "codesentry-webui", "ui": "/ui", "docs": "/docs"}


def cleanup_mtime_cache() -> None:  # pragma: no cover
    shutil.rmtree(_work_root() / ".tmp", ignore_errors=True)
