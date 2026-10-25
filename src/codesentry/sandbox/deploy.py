"""沙箱部署 Agent（M6.2）：上传后默认在 Docker 中构建/启动目标（host 模式仅绑 127.0.0.1）。"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    "maven": {
        "image": "maven:3.9-eclipse-temurin-8",
        "port": 8080,
        "command": (
            "sh -lc 'mvn -q -DskipTests package || exit 2; "
            "if ls target/*.jar >/dev/null 2>&1; then "
            "JAR=$(ls target/*.jar | head -1); "
            "for J in \"$JAVA_HOME/bin/java\" java /usr/lib/jvm/*/bin/java "
            "/opt/java/openjdk/bin/java; do "
            "[ -x \"$J\" ] && exec \"$J\" -jar \"$JAR\"; done; "
            "echo JAVA_NOT_FOUND; exit 5; "
            "elif ls target/*.war >/dev/null 2>&1; then "
            "echo WAR_PACKAGING_REQUIRES_TOMCAT; exit 3; "
            "else echo NO_JAR_OR_WAR; exit 4; fi'"
        ),
    },
    "gradle": {
        "image": "gradle:8-jdk17",
        "port": 8080,
        "command": (
            "sh -lc 'gradle bootJar --no-daemon -q && "
            "exec java -jar $(ls build/libs/*.jar | head -1)'"
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
    if "pom.xml" in names:
        return "maven"
    if "build.gradle" in names or "build.gradle.kts" in names:
        return "gradle"
    if "requirements.txt" in names or any(n.endswith(".py") for n in names):
        return "python"
    if "composer.json" in names or any(n.endswith(".php") for n in names):
        return "php"
    if "package.json" in names:
        return "javascript"
    return None


def find_dockerfile(root: Path) -> Path | None:
    """根目录优先，其次常见子目录，最后在 4 层内递归查找。"""
    preferred = [
        root / "Dockerfile",
        root / "docker" / "Dockerfile",
        root / "src" / "main" / "docker" / "Dockerfile",
        root / "dockerfiles" / "Dockerfile",
    ]
    for candidate in preferred:
        if candidate.is_file():
            return candidate
    try:
        for candidate in root.rglob("Dockerfile"):
            if candidate.is_file() and len(candidate.relative_to(root).parts) <= 4:
                return candidate
    except OSError:
        pass
    return None


def detect_port(root: Path, default: int) -> int:
    """Dockerfile EXPOSE / app.py 常见端口；失败回退 default。"""
    try:
        df = find_dockerfile(root)
        if df is not None:
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


def local_java_image() -> str | None:
    """优先复用本机已有 Java/Maven 镜像，避免外部 registry 不可达。"""
    try:
        import docker

        client = docker.from_env(timeout=15)
        tags = [tag for image in client.images.list() for tag in (image.tags or [])]
        client.close()
    except Exception:  # noqa: BLE001
        return None
    scored = []
    for tag in tags:
        low = tag.lower()
        if "squid" in low:
            continue
        score = 0
        if "maven" in low:
            score += 3
        if any(k in low for k in ("openjdk", "temurin", "jdk")):
            score += 3
        if "8" in low or "java8" in low:
            score += 2
        if score >= 5:
            scored.append((score, tag))
    return max(scored)[1] if scored else None


def choose_java_image(explicit: str = "", *, allow_remote: bool = False) -> str | None:
    if explicit:
        return explicit
    local = local_java_image()
    if local:
        return local
    if allow_remote:
        return "maven:3.9-eclipse-temurin-8"
    return None


def _image_exists(client, image: str) -> bool:
    try:
        client.images.get(image)
        return True
    except Exception:  # noqa: BLE001 - ImageNotFound/daemon error 都视为本地不可用
        return False


def ensure_image(client, image: str, policy: str = "missing") -> bool:
    """按 never/missing/always 策略确保镜像可用；never 缺失返回 False。"""
    policy = policy if policy in ("never", "missing", "always") else "missing"
    exists = _image_exists(client, image)
    if policy == "never":
        return exists
    if policy == "always" or not exists:
        client.images.pull(image)
    return True


def detect_runtime_dependencies(root: Path) -> list[str]:
    """从 application*.yml/properties 粗略识别 MySQL/Redis 等外部依赖。"""
    deps: list[str] = []
    try:
        files = list(root.rglob("application*.yml")) + list(root.rglob("application*.yaml"))
        files += list(root.rglob("application*.properties"))
        text = "\n".join(f.read_text(errors="replace")[:20000] for f in files[:20]).lower()
        for name, marker in (
            ("MySQL", "mysql"), ("Redis", "redis"), ("PostgreSQL", "postgres"),
            ("RabbitMQ", "rabbitmq"), ("Elasticsearch", "elasticsearch"),
        ):
            if marker in text and name not in deps:
                deps.append(name)
    except Exception:  # noqa: BLE001, S110
        pass
    return deps


class DockerDeployer:
    def __init__(self, scan_id: int, repo: str, *, poc_run: str = "off",
                 timeout_s: int = 120, mem_mb: int = 512, cpu: float = 1.0,
                 images: dict[str, str] | None = None,
                 internal_network: bool | None = None,
                 network_mode: str | None = None,
                 default_port: int = 8080,
                 workspace_root: str | Path | None = None,
                 java_image: str = "",
                 maven_image: str = "",
                 allow_remote_images: bool = False,
                 image_pull: str = "missing",
                 auto_dependencies: bool = True,
                 dependency_images: dict[str, str] | None = None,
                 dependency_timeout_s: int = 90) -> None:
        self.scan_id = int(scan_id)
        self.repo = repo
        self.poc_run = poc_run
        self.timeout_s = int(timeout_s)
        self.mem_mb = int(mem_mb)
        self.cpu = float(cpu)
        self.images = dict(images or {})
        self.java_image = java_image
        self.maven_image = maven_image
        self.allow_remote_images = allow_remote_images
        self.image_pull = image_pull if image_pull in ("never", "missing", "always") else "missing"
        self.auto_dependencies = bool(auto_dependencies)
        self.dependency_images = dict(dependency_images or {})
        self.dependency_timeout_s = int(dependency_timeout_s)
        self._dependencies: Any = None
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

    def _build_image(self, client, root: Path, dockerfile: str = "Dockerfile") -> tuple[str, str]:
        tag = f"codesentry-target-{self.scan_id}:latest"
        image, logs = client.images.build(
            path=str(root), dockerfile=dockerfile, tag=tag, rm=True,
            timeout=max(180, self.timeout_s + 90),
            pull=self.image_pull == "always",
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
        df = find_dockerfile(root)
        detected = detect_recipe(str(root))
        use_dockerfile = df is not None
        if use_dockerfile and df is not None and detected in ("maven", "gradle"):
            text = df.read_text(errors="replace").lower()
            need_build = "mvn" in text or "gradle" in text or "multi-stage" in text
            if not need_build:
                # Dockerfile 只 ADD 预构建产物，直接构建会失败；改用语言配方先构建
                use_dockerfile = False
        recipe_name: str | None
        command: str | None
        entrypoint: str | None
        volumes: dict | None
        working_dir: str | None
        if use_dockerfile and df is not None:
            try:
                rel = str(df.relative_to(root))
                image, build_log = self._build_image(client, root, rel)
            except Exception as e:  # noqa: BLE001
                return DeployResult("disabled", f"Dockerfile 构建失败：{str(e)[:300]}")
            command = None
            entrypoint = None
            port = detect_port(root, self.default_port)
            volumes = None
            working_dir = None
            recipe_name = "dockerfile"
        else:
            recipe_name = detected
            if recipe_name is None:
                return DeployResult("disabled", f"未识别部署方式（Dockerfile/语言配方）：{root}")
            recipe = RECIPES.get(recipe_name)
            if recipe is None:
                return DeployResult("disabled", f"未支持的语言配方：{recipe_name}")
            image = self.images.get(recipe_name) or recipe["image"]
            if recipe_name in ("maven", "gradle"):
                image = (self.maven_image or self.java_image
                         or choose_java_image("", allow_remote=self.allow_remote_images)
                         or image)
            command = recipe["command"]
            entrypoint = ""
            port = detect_port(root, recipe["port"])
            workspace = self._prepare_workspace(root)
            volumes = {str(workspace.resolve()): {"bind": "/target", "mode": "rw"}}
            working_dir = "/target"

        try:
            if not use_dockerfile:
                try:
                    if not ensure_image(client, image, self.image_pull):
                        return DeployResult(
                            "disabled",
                            f"镜像 {image} 本地不存在且 deploy_image_pull=never",
                            meta={"recipe": recipe_name, "image": image},
                        )
                except Exception as e:  # noqa: BLE001
                    return DeployResult(
                        "disabled", f"镜像 {image} 不可用（pull={self.image_pull}）：{str(e)[:200]}",
                        meta={"recipe": recipe_name, "image": image},
                    )
            try:
                self._network = client.networks.get(self.network_name)
            except Exception:  # noqa: BLE001
                self._network = client.networks.create(
                    self.network_name, driver="bridge", internal=self.internal_network
                )
            dependency_env: dict[str, str] = {}
            dependency_results: list[dict] = []
            if self.auto_dependencies:
                from codesentry.sandbox.dependencies import DependencyManager

                self._dependencies = DependencyManager(
                    client, self.network_name, self.scan_id, root=root,
                    timeout_s=self.dependency_timeout_s, pull_policy=self.image_pull,
                    allow_remote=self.allow_remote_images,
                    images=self.dependency_images,
                )
                dependency_results = self._dependencies.ensure_all()
                dependency_env = dict(self._dependencies.env)
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
            target_env = dict(dependency_env)
            if recipe_name in ("maven", "gradle"):
                # Spring Boot 项目常见 server.port=80/8081/8082；统一到容器 8080，
                # 否则宿主映射、健康检查和反向代理都会错位。
                target_env.setdefault("SERVER_PORT", str(port))
                target_env.setdefault("SPRING_PROFILES_ACTIVE", "dev")
            if target_env:
                kwargs["environment"] = target_env
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
            runtime_deps = detect_runtime_dependencies(root)
            if self._dependencies is not None:
                log += "；依赖：" + json.dumps(dependency_results, ensure_ascii=False)[:1200]
                if any(not d.get("ok") for d in dependency_results):
                    status = "degraded"
                    log += "；依赖未全部就绪"
            elif runtime_deps and status != "ready":
                status = "degraded"
                log += f"；检测到外部依赖 {', '.join(runtime_deps)}，容器可能因依赖未就绪而启动失败"
            if not target_url:
                try:
                    log += f"；日志：{container.logs(tail=30).decode('utf-8', 'replace')[-600:]}"
                except Exception:  # noqa: BLE001, S110
                    pass
                status = "degraded"
            return DeployResult(
                status, log[:4000], target_url=target_url,
                container_id=container.id[:12], network=self.network_name,
                meta={"recipe": recipe_name, "image": image, "port": host_port or port,
                      "dependencies": dependency_results,
                      "dependency_env": sorted(dependency_env)},
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
            for cmd in (["python", "-c", code], ["wget", "-q", "-O", "-", target_url],
                        ["curl", "-fsS", target_url]):
                try:
                    r = container.exec_run(cmd, demux=False)
                    if r.exit_code == 0:
                        return "ready"
                except Exception:  # noqa: BLE001, S110
                    pass
            time.sleep(1.0)
        return "degraded"

    def cleanup(self) -> None:
        if self._dependencies is not None:
            try:
                self._dependencies.cleanup()
            except Exception:  # noqa: BLE001, S110
                pass
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
            for c in client.containers.list(
                all=True, filters={"label": f"codesentry.scan_id={scan_id}"}
            ):
                if c.name.startswith("codesentry-dep-"):
                    c.stop(timeout=3)
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
        java_image=settings.deploy_java_image,
        maven_image=settings.deploy_maven_image,
        allow_remote_images=settings.deploy_image_allow_remote,
        image_pull=settings.deploy_image_pull,
        auto_dependencies=settings.deploy_auto_dependencies,
        dependency_images={
            "mysql": settings.deploy_dependency_mysql_image,
            "redis": settings.deploy_dependency_redis_image,
            "postgres": settings.deploy_dependency_postgres_image,
        },
        dependency_timeout_s=settings.deploy_dependency_timeout_s,
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
