"""沙箱部署 Agent（M6.2）：按语言配方在 Docker 中构建/启动目标。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import httpx

RECIPES: dict[str, dict] = {
    "python": {
        "image": "python:3.12-slim",
        "port": 8080,
        "command": (
            "sh -lc 'if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi; "
            "if [ -f app.py ]; then python app.py; elif [ -f main.py ]; then python main.py; "
            "elif [ -f manage.py ]; then python manage.py runserver 0.0.0.0:8080; "
            "else python -m http.server 8080; fi'"
        ),
    },
    "php": {
        "image": "php:8.3-cli",
        "port": 8080,
        "command": "php -S 0.0.0.0:8080 -t /target",
    },
    "javascript": {
        "image": "node:20-slim",
        "port": 3000,
        "command": (
            "sh -lc 'if [ -f package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi; "
            "if npm run | grep -q start; then npm start; else node server.js; fi'"
        ),
    },
}


@dataclass
class DeployResult:
    status: str  # ready|degraded|built|disabled
    log: str = ""
    target_url: str = ""
    container_id: str = ""
    network: str = ""
    meta: dict = field(default_factory=dict)


def detect_recipe(repo: str) -> str | None:
    p = Path(repo)
    if not p.exists():
        return None
    names = {f.name for f in p.iterdir() if f.is_file()}
    if "requirements.txt" in names or any(n.endswith(".py") for n in names):
        return "python"
    if "composer.json" in names or any(n.endswith(".php") for n in names):
        return "php"
    if "package.json" in names:
        return "javascript"
    return None


class DockerDeployer:
    def __init__(self, scan_id: int, repo: str, *, poc_run: str = "off",
                 timeout_s: int = 120, mem_mb: int = 512, cpu: float = 1.0) -> None:
        self.scan_id = int(scan_id)
        self.repo = repo
        self.poc_run = poc_run
        self.timeout_s = int(timeout_s)
        self.mem_mb = int(mem_mb)
        self.cpu = float(cpu)
        self.container_name = f"codesentry-target-{self.scan_id}"
        self.network_name = f"codesentry-net-{self.scan_id}"
        self._container = None
        self._network = None

    def _client(self):
        import docker

        client = docker.from_env()
        client.ping()
        return client

    def deploy(self) -> DeployResult:
        recipe_name = detect_recipe(self.repo)
        if recipe_name is None:
            return DeployResult("disabled", f"未识别部署配方：{self.repo}")
        recipe = RECIPES[recipe_name]
        if self.poc_run == "off":
            return DeployResult(
                "built",
                f"POC_RUN=off：已选择 {recipe_name} 配方（{recipe['image']}），仅构建配置不启动服务",
                meta={"recipe": recipe_name, "image": recipe["image"]},
            )
        try:
            client = self._client()
        except Exception as e:  # noqa: BLE001 - Docker 不可用
            return DeployResult("disabled", f"Docker 不可用：{str(e)[:200]}")

        try:
            try:
                self._network = client.networks.get(self.network_name)
            except Exception:  # noqa: BLE001
                self._network = client.networks.create(self.network_name, driver="bridge", internal=True)
            container = client.containers.run(
                recipe["image"],
                recipe["command"],
                name=self.container_name,
                detach=True,
                network=self.network_name,
                ports={f"{recipe['port']}/tcp": None},
                mem_limit=f"{self.mem_mb}m",
                nano_cpus=int(self.cpu * 1_000_000_000),
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                volumes={str(Path(self.repo).resolve()): {"bind": "/target", "mode": "ro"}},
                working_dir="/target",
                labels={"codesentry.scan_id": str(self.scan_id), "codesentry.role": "target"},
                auto_remove=False,
            )
            self._container = container
            container.reload()
            ports = (container.attrs.get("NetworkSettings", {}).get("Ports") or {})
            host_port = ports.get(f"{recipe['port']}/tcp", [{}])[0].get("HostPort", "")
            target_url = f"http://127.0.0.1:{host_port}/" if host_port else ""
            status = self._wait_healthy(target_url)
            return DeployResult(
                status,
                f"容器 {self.container_name} 已启动（{status}），target={target_url}",
                target_url=target_url,
                container_id=container.id[:12],
                network=self.network_name,
                meta={"recipe": recipe_name, "image": recipe["image"], "port": host_port},
            )
        except Exception as e:  # noqa: BLE001
            self.cleanup()
            return DeployResult("disabled", f"部署失败：{str(e)[:300]}")

    def _wait_healthy(self, target_url: str) -> str:
        if not target_url:
            return "degraded"
        import time

        deadline = time.time() + min(self.timeout_s, 120)
        while time.time() < deadline:
            try:
                r = httpx.get(target_url, timeout=2.0, follow_redirects=False)
                if 200 <= r.status_code < 500:
                    return "ready"
            except Exception:  # noqa: BLE001, S110
                pass
            time.sleep(1.0)
        return "degraded"

    def cleanup(self) -> None:
        try:
            if self._container is not None:
                self._container.stop(timeout=5)
                self._container.remove(force=True)
        except Exception:  # noqa: BLE001, S110
            pass
        try:
            if self._network is not None:
                self._network.remove()
        except Exception:  # noqa: BLE001, S110
            pass


def cleanup_scan(scan_id: int) -> None:
    try:
        import docker

        client = docker.from_env()
        for name in (f"codesentry-target-{scan_id}",):
            try:
                c = client.containers.get(name)
                c.stop(timeout=5)
                c.remove(force=True)
            except Exception:  # noqa: BLE001, S110
                pass
        try:
            client.networks.get(f"codesentry-net-{scan_id}").remove()
        except Exception:  # noqa: BLE001, S110
            pass
        client.close()
    except Exception:  # noqa: BLE001, S110
        pass


def run_deploy(state: dict) -> dict:
    from codesentry.config import get_settings

    scan_id = int(state.get("scan_id") or 0)
    repo = str(state.get("repo_path") or "")
    mode = state.get("poc_run") or get_settings().poc_run
    if not scan_id or not repo:
        return {"deploy_status": "disabled", "deploy_log": "缺少 scan_id/repo_path", "phase": "poc_gen"}
    deployer = DockerDeployer(
        scan_id, repo, poc_run=mode,
        timeout_s=get_settings().deploy_timeout_s,
        mem_mb=get_settings().deploy_mem_mb,
        cpu=get_settings().deploy_cpu,
    )
    try:
        result = deployer.deploy()
    except Exception as e:  # noqa: BLE001
        result = DeployResult("disabled", f"部署异常：{str(e)[:200]}")
    return {
        "deploy_status": result.status,
        "deploy_log": result.log[:4000],
        "target_url": result.target_url,
        "deploy": {
            "status": result.status,
            "target_url": result.target_url,
            "container_id": result.container_id,
            "network": result.network,
            "meta": result.meta,
        },
        "phase": "poc_gen",
    }
