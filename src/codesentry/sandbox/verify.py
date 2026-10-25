"""PoC 实证验证（M6.3）：PoC 自身声明 canary 占位符并产生证据。

占位符约定（由 PoCGenAgent 生成）：
- `{CANARY_CMD}`  → 替换为 `echo CODESENTRY-{nonce}`，输出含 nonce 即 confirmed
- `{CANARY_FILE}` → 替换为 `/tmp/codesentry-{nonce}`，随后检查文件存在
- `{CANARY_URL}`  → 替换为宿主 127.0.0.1 一次性 listener URL，命中回调即 confirmed

没有声明任何占位符 → 最高 plausible（不能仅凭容器可执行命令判定 verified）。
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass
class CanaryResult:
    ok: bool
    method: str = "none"
    nonce: str = ""
    log: str = ""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.hit = True  # type: ignore[attr-defined]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        return


class CanaryVerifier:
    def __init__(self, scan_id: int, target_url: str = "", container_name: str | None = None) -> None:
        self.scan_id = int(scan_id)
        self.target_url = target_url
        self.container_name = container_name or f"codesentry-target-{scan_id}"

    def _container(self):
        import docker

        client = docker.from_env()
        return client, client.containers.get(self.container_name)

    def _exec(self, script: str) -> str:
        client, container = self._container()
        try:
            out = ""
            for cmd in (["python", "-c", script], ["sh", "-c", script]):
                r = container.exec_run(cmd, demux=False)
                out = (r.output or b"").decode("utf-8", "replace")
                if r.exit_code == 0:
                    return out
            return out
        finally:
            client.close()

    def verify_echo(self, script: str, nonce: str) -> CanaryResult:
        if "{CANARY_CMD}" not in script:
            return CanaryResult(False, "canary", nonce, "PoC 未声明 {CANARY_CMD}")
        try:
            out = self._exec(script.replace("{CANARY_CMD}", f"echo CODESENTRY-{nonce}"))
            if f"CODESENTRY-{nonce}" in out:
                return CanaryResult(True, "canary", nonce, f"PoC 命令回显命中：{out[-200:]}")
            return CanaryResult(False, "canary", nonce, "PoC 执行但未回显 nonce")
        except Exception as e:  # noqa: BLE001
            return CanaryResult(False, "canary", nonce, f"canary 失败：{str(e)[:160]}")

    def verify_fs(self, script: str, nonce: str) -> CanaryResult:
        if "{CANARY_FILE}" not in script:
            return CanaryResult(False, "fs-effect", nonce, "PoC 未声明 {CANARY_FILE}")
        path = f"/tmp/codesentry-{nonce}"
        try:
            self._exec(script.replace("{CANARY_FILE}", path))
            out = self._exec(f"test -f {path} && echo CODESENTRY-{nonce}")
            if f"CODESENTRY-{nonce}" in out:
                return CanaryResult(True, "fs-effect", nonce, f"PoC 文件副作用命中：{path}")
            return CanaryResult(False, "fs-effect", nonce, "PoC 执行但文件不存在")
        except Exception as e:  # noqa: BLE001
            return CanaryResult(False, "fs-effect", nonce, f"fs-effect 失败：{str(e)[:160]}")

    def verify_listener(self, script: str, nonce: str) -> CanaryResult:
        if "{CANARY_URL}" not in script:
            return CanaryResult(False, "listener", nonce, "PoC 未声明 {CANARY_URL}")
        import os

        srv = ThreadingHTTPServer(("0.0.0.0", 0), _Handler)
        srv.hit = False  # type: ignore[attr-defined]
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            host = os.environ.get("CODESENTRY_CANARY_HOST", "host.docker.internal")
            url = f"http://{host}:{srv.server_port}/{nonce}"
            try:
                self._exec(script.replace("{CANARY_URL}", url))
            except Exception:  # noqa: BLE001, S110 - 回调可能先于异常发生
                pass
            if getattr(srv, "hit", False):
                return CanaryResult(True, "listener", nonce, f"PoC HTTP 回调命中：{url}")
            return CanaryResult(False, "listener", nonce, "PoC 执行但未收到回调")
        finally:
            srv.shutdown()
            srv.server_close()

    def verify_poc(self, poc_script: str) -> CanaryResult:
        nonce = uuid.uuid4().hex[:16]
        candidates = []
        if "{CANARY_CMD}" in poc_script:
            candidates.append(self.verify_echo)
        if "{CANARY_FILE}" in poc_script:
            candidates.append(self.verify_fs)
        if "{CANARY_URL}" in poc_script:
            candidates.append(self.verify_listener)
        if not candidates:
            return CanaryResult(
                False, "none", nonce,
                "PoC 未声明 canary 占位符（{CANARY_CMD}/{CANARY_FILE}/{CANARY_URL}），最高 plausible",
            )
        last = CanaryResult(False, "none", nonce, "未命中")
        for check in candidates:
            res = check(poc_script, nonce)
            if res.ok:
                return res
            last = res
        return last


def verify_poc(scan_id: int, script: str, target_url: str = "",
               container_name: str | None = None) -> CanaryResult:
    try:
        return CanaryVerifier(scan_id, target_url, container_name).verify_poc(script)
    except Exception as e:  # noqa: BLE001
        return CanaryResult(False, "none", "", f"验证异常：{str(e)[:200]}")
