"""沙箱部署 Agent（M6.2）：上传后默认在 Docker 中构建/启动目标（host 模式仅绑 127.0.0.1）。"""

from __future__ import annotations

import re
import shutil
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

MARKERS = {
    "Dockerfile", "docker-compose.yml", "compose.yml", "requirements.txt", "package.json",
    "composer.json", "pom.xml", "app.py", "main.py", "manage.py", "index.php",
}


@dataclass
class DeployResult:
    status: str  # ready|degraded|built|disabled
    log: str = ""
    target_url: str = ""
    container_id: str = ""
    network: str = ""
    meta: dict = field(default_factory=dict)


def resolve_project_root(repo: str) -> Path:
    """兼容 zip 内单层/双层根目录。"""
    p = Path(repo)
    if not p.exists():
        return p
    if any((p / m).exists() for m in MARKERS):
        return p
    for child in p.iterdir():
        if child.is_dir() and any((child / m).exists() for m in MARKERS):
            return child
    for child in p.iterdir():
        if not child.is_dir():
            continue
        for grand in child.iterdir():
            if grand.is_dir() and any((grand / m).exists() for m in MARKERS):
                return grand
    return p


def detect_recipe(repo: str) -> str | None:
    p = resolve_project_root(repo)
    names = {f.name for f in p.iterdir() if f.is_file()} if p.exists() else set()
    if "requirements.txt" in names or any(n.endswith(".py") for n in names):
        return "python"
    if "composer.json" in names or any(n.endswith(".php") for n in names):
        return "php"
    if "package.json" in names:
        return "javascript"
    return None


def detect_port(root: Path, default: int) -> int:
    """Dockerfile EXPOSE / app.py 常见端口；失败回退 default。"""
    try:
        df = root / "Dockerfile"
        if df.is_file():
            m = re.search(r"^\s*EXPOSE\s+(\d{2,5})", df.read_text(errors="replace"), re.MULTILINE)
            if m:
                return int(m.group(1))
        for name in ("app.py", "main.py", "server.py"):
            f = root / name
            if not f.is_file():
                continue
            text = f.read_text(errors="replace")
            for pat in (r"port\s*=\s*(\d{3,5})", r"\.run\([^)]*?(\d{4,5})", r":(\d{4,5})"):
                m = re.search(pat, text)
                if m:
                    return int(m.group(1))
    except Exception:  # noqa: BLE001, S110
        pass
    return default


class DockerDeployer:
    def __init__(self, scan_id: int, repo: str, *, poc_run: str = "off",
                 timeout_s: int = 120, mem_mb: int = 512, cpu: float = 1.0,
                 images: dict[str, str] | None = None,
                 internal_network: bool | None = None,
                 network_mode: str | None = None,
                 default_port: int = 8080,
                 workspace_root: str | Path | None = None) -> None:
        self.scan_id = int(scan_id)
        self.repo = repo
        self.poc_run = poc_run
        self.timeout_s = int(timeout_s)
        self.mem_mb = int(mem_mb)
        self.cpu = float(cpu)
        self.images = dict(images or {})
        if network_mode is not None:
            self.internal_network = network_mode == "internal"
        else:
            self.internal_network = True if internal_network is None else bool(internal_network)
        self.default_port = int(default_port)
        self.container_name = f"codesentry-target-{self.scan_id}"
        self.network_name = f"codesentry-net-{self.scan_id}"
        base = Path(workspace_root) if workspace_root else Path(".codesentry") / "deploy"
        self.workspace = base / str(self.scan_id)
        self._container = None
        self._network = None

    def _client(self):
        import docker

        client = docker.from_env(timeout=max(180, self.timeout_s + 90))
        client.ping()
        return client

    def _prepare_workspace(self, root: Path) -> Path:
        if self.workspace.exists():
            shutil.rmtree(self.workspace, ignore_errors=True)
        self.workspace.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            root, self.workspace, dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(
                "node_modules", "venv", ".venv", ".git", "__pycache__", "*.pyc"
            ),
        )
        return self.workspace

    def _build_image(self, client, root: Path) -> tuple[str, str]:
        tag = f"codesentry-target-{self.scan_id}:latest"
        image, logs = client.images.build(
            path=str(root), dockerfile="Dockerfile", tag=tag, rm=True,
            timeout=max(180, self.timeout_s + 90),
        )
        tail = []
        for chunk in logs:
            if isinstance(chunk, dict) and chunk.get("stream"):
                tail.append(str(chunk["stream"]))
        return image.id, "".join(tail)[-2000:]

    def deploy(self) -> DeployResult:
        root = resolve_project_root(self.repo)
        if not root.exists():
            return DeployResult("disabled", f"源码目录不存在：{self.repo}")
        try:
            client = self._client()
        except Exception as e:  # noqa: BLE001
            return DeployResult("disabled", f"Docker 不可用：{str(e)[:200]}")

        build_log = ""
        dockerfile = root / "Dockerfile"
        use_dockerfile = dockerfile.is_file()
        recipe_name: str | None
        command: str | None
        entrypoint: str | None
        volumes: dict | None
        working_dir: str | None
        if use_dockerfile:
            try:
                image, build_log = self._build_image(client, root)
            except Exception as e:  # noqa: BLE001
                return DeployResult("disabled", f"Dockerfile 构建失败：{str(e)[:300]}")
            command = None
            entrypoint = None
            port = detect_port(root, self.default_port)
            volumes = None
            working_dir = None
            recipe_name = "dockerfile"
        else:
            recipe_name = detect_recipe(str(root))
            if recipe_name is None:
                return DeployResult("disabled", f"未识别部署方式（Dockerfile/语言配方）：{root}")
            recipe = RECIPES[recipe_name]
            image = self.images.get(recipe_name) or recipe["image"]
            command = recipe["command"]
            entrypoint = ""
            port = detect_port(root, recipe["port"])
            workspace = self._prepare_workspace(root)
            volumes = {str(workspace.resolve()): {"bind": "/target", "mode": "rw"}}
            working_dir = "/target"

        try:
            try:
                self._network = client.networks.get(self.network_name)
            except Exception:  # noqa: BLE001
                self._network = client.networks.create(
                    self.network_name, driver="bridge", internal=self.internal_network
                )
            publish = None if self.internal_network else {f"{port}/tcp": ("127.0.0.1", None)}
            kwargs = {
                "name": self.container_name,
                "detach": True,
                "network": self.network_name,
                "ports": publish,
                "mem_limit": f"{self.mem_mb}m",
                "nano_cpus": int(self.cpu * 1_000_000_000),
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges"],
                "labels": {"codesentry.scan_id": str(self.scan_id), "codesentry.role": "target"},
                "auto_remove": False,
            }
            if command is not None:
                kwargs["command"] = command
            if entrypoint is not None:
                kwargs["entrypoint"] = entrypoint
            if volumes:
                kwargs["volumes"] = volumes
            if working_dir:
                kwargs["working_dir"] = working_dir
            container = client.containers.run(image, **kwargs)
            self._container = container
            container.reload()

            if self.internal_network:
                target_url = f"http://127.0.0.1:{port}/"
                status = self._wait_healthy_container(container, target_url)
                host_port = ""
            else:
                ports = (container.attrs.get("NetworkSettings", {}).get("Ports") or {})
                port_list = ports.get(f"{port}/tcp") or []
                host_port = port_list[0].get("HostPort", "") if port_list else ""
                target_url = f"http://127.0.0.1:{host_port}/" if host_port else ""
                status = self._wait_healthy(target_url) if target_url else "degraded"

            log = f"{build_log}\n" if build_log else ""
            log += f"容器 {self.container_name}（{recipe_name}）{status}，target={target_url or '—'}"
            if not target_url:
                try:
                    log += f"；日志：{container.logs(tail=30).decode('utf-8', 'replace')[-600:]}"
                except Exception:  # noqa: BLE001, S110
                    pass
                status = "degraded"
            return DeployResult(
                status, log[:4000], target_url=target_url,
                container_id=container.id[:12], network=self.network_name,
                meta={"recipe": recipe_name, "image": image, "port": host_port or port},
            )
        except Exception as e:  # noqa: BLE001
            tail = ""
            try:
                if self._container is not None:
                    tail = self._container.logs(tail=30).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001, S110
                pass
            self.cleanup()
            return DeployResult("disabled", f"部署失败：{str(e)[:300]} | 日志：{tail[-600:]}")

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

    def _wait_healthy_container(self, container, target_url: str) -> str:
        import time

        code = (
            "import urllib.request;"
            f"urllib.request.urlopen({target_url!r}, timeout=2);"
            "print('ok')"
        )
        deadline = time.time() + min(self.timeout_s, 120)
        while time.time() < deadline:
            for cmd in (["python", "-c", code], ["wget", "-q", "-O", "-", target_url]):
                try:
                    r = container.exec_run(cmd, demux=False)
                    if r.exit_code == 0:
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
        shutil.rmtree(self.workspace, ignore_errors=True)


def cleanup_scan(scan_id: int) -> None:
    try:
        import docker

        client = docker.from_env(timeout=120)
        try:
            c = client.containers.get(f"codesentry-target-{scan_id}")
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
    try:
        from codesentry.config import get_settings

        shutil.rmtree(Path(get_settings().work_dir) / "deploy" / str(scan_id), ignore_errors=True)
    except Exception:  # noqa: BLE001, S110
        pass


def run_deploy(state: dict) -> dict:
    from codesentry.config import get_settings

    settings = get_settings()
    scan_id = int(state.get("scan_id") or 0)
    repo = str(state.get("repo_path") or "")
    if not scan_id or not repo:
        return {"deploy_status": "disabled", "deploy_log": "缺少 scan_id/repo_path", "phase": "poc_gen"}
    if not settings.deploy_enabled:
        return {"deploy_status": "disabled", "deploy_log": "DEPLOY_ENABLED=false", "phase": "poc_gen"}
    deployer = DockerDeployer(
        scan_id, repo,
        timeout_s=settings.deploy_timeout_s,
        mem_mb=settings.deploy_mem_mb,
        cpu=settings.deploy_cpu,
        images={
            "python": settings.deploy_python_image,
            "php": settings.deploy_php_image,
            "javascript": settings.deploy_javascript_image,
        },
        network_mode=settings.deploy_network_mode,
        default_port=settings.deploy_port,
        workspace_root=Path(settings.work_dir) / "deploy",
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
