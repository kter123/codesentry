"""浏览器级 UI smoke（Safari WebDriver，P0-7）。

启动本地后端（托管 /ui 静态资源），逐路由检查 #app 是否有渲染内容、标题与关键文案。
Safari 未启用远程自动化时输出 BLOCKED 与具体原因，不伪造 PASS。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _req(method: str, url: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode() or "{}")


def _wait(url: str, timeout_s: float = 20) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            _req("GET", url)
            return True
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return False


class Safari:
    def __init__(self, port: int = 4444):
        self.base = f"http://127.0.0.1:{port}"
        self.session = ""
        self.proc = None

    def start(self) -> None:
        self.proc = subprocess.Popen(
            ["safaridriver", "--port", str(self.base.rsplit(":", 1)[1])],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
        if not _wait(self.base + "/status", 5):
            err = ""
            if self.proc.stderr:
                err = self.proc.stderr.read()[-500:]
            raise RuntimeError(f"safaridriver 未就绪：{err}")
        body = _req("POST", self.base + "/session", {
            "capabilities": {"alwaysMatch": {"browserName": "safari"}},
        })
        self.session = body.get("value", {}).get("sessionId") or ""
        if not self.session:
            raise RuntimeError(f"创建 Safari session 失败：{body}")

    def get(self, url: str) -> None:
        _req("POST", f"{self.base}/session/{self.session}/url", {"url": url})

    def script(self, js: str) -> object:
        return _req("POST", f"{self.base}/session/{self.session}/execute/sync",
                    {"script": js, "args": []}).get("value")

    def quit(self) -> None:
        try:
            if self.session:
                _req("DELETE", f"{self.base}/session/{self.session}")
        except Exception:  # noqa: BLE001, S110
            pass
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--driver-port", type=int, default=4444)
    parser.add_argument("--keep-server", action="store_true")
    args = parser.parse_args()

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["CODESENTRY_SCHEDULER_ENABLED"] = "false"
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "codesentry.web.server:app",
         "--host", "127.0.0.1", "--port", str(args.port), "--log-level", "warning"],
        cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    driver = Safari(args.driver_port)
    try:
        if not _wait(f"http://127.0.0.1:{args.port}/api/health", 20):
            print("BLOCKED: 后端未就绪")
            return 2
        try:
            scans = _req("GET", f"http://127.0.0.1:{args.port}/api/scans")
        except Exception:  # noqa: BLE001
            scans = []
        routes = [
            "/ui/", "/ui/scans", "/ui/projects", "/ui/reviews", "/ui/agents",
            "/ui/agents/recon", "/ui/llm", "/ui/usage", "/ui/prompts", "/ui/skills",
            "/ui/kb", "/ui/rules", "/ui/orchestration", "/ui/audit", "/ui/settings",
            "/ui/users", "/ui/login",
        ]
        if scans:
            sid = scans[0]["id"]
            routes.extend([f"/ui/scans/{sid}", f"/ui/scans/{sid}/graph?path_id=1"])
        try:
            driver.start()
            results = []
            for route in routes:
                url = f"http://127.0.0.1:{args.port}{route}"
                driver.get(url)
                time.sleep(0.8)
                info = driver.script(
                    "const app=document.getElementById('app');"
                    "return {children: app?app.children.length:0,"
                    " title: document.title,"
                    " text: (document.body.innerText||'').slice(0,400)};"
                )
                ok = bool(info and info.get("children", 0) > 0)
                if route == "/ui/login":
                    ok = ok and "登录" in str(info.get("text") or "")
                results.append({"route": route, "ok": ok, "title": info.get("title"),
                                "children": info.get("children"),
                                "text": str(info.get("text") or "")[:120]})
            passed = sum(1 for r in results if r["ok"])
            print(json.dumps({"passed": passed, "total": len(results), "results": results},
                             ensure_ascii=False, indent=2))
            return 0 if passed == len(results) else 1
        except Exception as e:  # noqa: BLE001
            print(f"BLOCKED: Safari WebDriver 不可用：{e}")
            print("提示：首次使用需执行 `safaridriver --enable`（需要管理员权限）。")
            return 3
    finally:
        driver.quit()
        if not args.keep_server:
            server.terminate()
            try:
                server.wait(timeout=8)
            except subprocess.TimeoutExpired:
                server.kill()


if __name__ == "__main__":
    raise SystemExit(main())
