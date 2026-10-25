"""DeployAgent：Agent 读仓库、决定构建方式、生成 Dockerfile、构建/启动/探测。"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

SYSTEM = """你是 CodeSentry 的部署 Agent。你的任务是把上传的源码在 Docker 中跑起来。

工作方式：
1. 先用 list_files / read_file / inspect 看清项目结构、构建文件和现有 Dockerfile。
2. 自己决定部署策略（Maven/Gradle/npm/pip/php/Dockerfile/静态站点）。
3. 用 write_dockerfile 写一份**自包含**的 Dockerfile（必须包含构建步骤，不能依赖仓库里未构建的产物）。
4. 用 docker_build 构建；失败就看日志修改 Dockerfile，最多重试 3 次。
5. 用 docker_run 启动并用 probe/health 验证；成功调用 finish。

工具：
list_files / read_file / inspect / local_images / detect_dependencies / ensure_dependency / write_dockerfile / docker_build / docker_run / docker_logs / probe / finish

依赖：若项目需要 MySQL/Redis/PostgreSQL，先 detect_dependencies，再 ensure_dependency；
依赖会与目标容器在同一 Docker network，并自动注入 MYSQL_HOST/MYSQL_PORT/REDIS_HOST 等 env。
不要等待人工提供数据库；自行决定并启动依赖，失败就如实 degraded。

约束：
- 只在 Docker 内构建与运行；不要请求宿主 shell。
- **优先使用 local_images 已存在的镜像**；不要使用不可达的镜像代理（如 daocloud 403）。
- Java 项目：`FROM` 必须使用 java_images 列表中的镜像（例如本地已有的 maven+openjdk），不得写未列出的 `openjdk:8-jre`。
- 端口用 8080（或项目明确端口），只绑定 127.0.0.1。
- 构建失败时读取日志修正，不要凭空猜。
- 证据不足就如实 finish(status="disabled", notes="...")。

最终必须输出：
{"status": "ready|degraded|disabled", "target_url": "...", "notes": "一句话"}
"""


def _parse_final(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


class DeploySession:
    def __init__(self, state: dict, settings) -> None:
        from codesentry.sandbox.deploy import resolve_project_root

        self.state = state
        self.settings = settings
        self.scan_id = int(state.get("scan_id") or 0)
        self.repo = str(state.get("repo_path") or "")
        self.root = resolve_project_root(self.repo)
        self.build_dir = (
            Path(settings.work_dir) / "deploy" / str(self.scan_id) / "agent-build"
        )
        self.container = None
        self.image = ""
        self.target_url = ""
        self.status = ""
        self.notes = ""
        self.plan: dict = {}
        self.build_log = ""
        self.dependency_env: dict[str, str] = {}
        self.dependency_results: list[dict] = []
        self.network = f"codesentry-net-{self.scan_id}"
        self._dependency_manager: Any = None
        self._prepare()

    def _prepare(self) -> None:
        if not self.root.exists():
            return
        if self.build_dir.exists():
            shutil.rmtree(self.build_dir, ignore_errors=True)
        self.build_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            self.root, self.build_dir, dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(
                "node_modules", "venv", ".venv", ".git", "__pycache__", "*.pyc",
                "target", "build", "dist",
            ),
        )

    def tools(self) -> dict:
        return {
            "list_files": self.list_files,
            "read_file": self.read_file,
            "inspect": self.inspect,
            "local_images": self.local_images,
            "detect_dependencies": self.detect_dependencies,
            "ensure_dependency": self.ensure_dependency,
            "write_dockerfile": self.write_dockerfile,
            "docker_build": self.docker_build,
            "docker_run": self.docker_run,
            "docker_logs": self.docker_logs,
            "probe": self.probe,
            "finish": self.finish,
        }

    def list_files(self, limit: int = 200) -> str:
        try:
            rows = []
            for path in sorted(self.root.rglob("*")):
                if path.is_dir() or ".git" in path.parts:
                    continue
                rel = str(path.relative_to(self.root))
                if rel.count("/") > 5:
                    continue
                rows.append(rel)
                if len(rows) >= limit:
                    break
            return json.dumps(rows, ensure_ascii=False)
        except OSError as exc:
            return f"ERROR: {exc}"

    def read_file(self, path: str, start: int = 1, end: int = 200) -> str:
        target = (self.root / path).resolve()
        if self.root.resolve() not in target.parents and target != self.root.resolve():
            return "DENIED: path escapes repo"
        try:
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            return f"ERROR: {exc}"
        start = max(1, int(start))
        end = min(len(lines), max(start, int(end)))
        return "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))[:8000]

    def inspect(self) -> str:
        names = ("pom.xml", "build.gradle", "build.gradle.kts", "package.json",
                 "requirements.txt", "pyproject.toml", "composer.json", "Dockerfile")
        out = {}
        for name in names:
            for path in self.root.rglob(name):
                if ".git" in path.parts:
                    continue
                rel = str(path.relative_to(self.root))
                try:
                    out[rel] = path.read_text(errors="replace")[:3000]
                except OSError:
                    continue
        return json.dumps(out, ensure_ascii=False)[:12000]

    def local_images(self, limit: int = 60) -> str:
        try:
            client = self._client()
            rows: list[str] = []
            for image in client.images.list()[: int(limit)]:
                tags = image.tags or [image.short_id]
                rows.extend(tags)
            return json.dumps(sorted(set(rows))[: int(limit)], ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: {exc}"

    def detect_dependencies(self) -> str:
        from codesentry.sandbox.dependencies import DependencyManager

        try:
            return json.dumps(DependencyManager.detect(self.root), ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: {exc}"

    def ensure_dependency(self, kind: str) -> str:
        from codesentry.sandbox.dependencies import DependencyManager

        try:
            client = self._client()
            try:
                client.networks.get(self.network)
            except Exception:  # noqa: BLE001
                client.networks.create(
                    self.network, driver="bridge",
                    internal=self.settings.deploy_network_mode == "internal",
                )
            if self._dependency_manager is None:
                self._dependency_manager = DependencyManager(
                    client, self.network, self.scan_id, root=self.root,
                    timeout_s=int(self.settings.deploy_dependency_timeout_s),
                    pull_policy=self.settings.deploy_image_pull,
                    allow_remote=self.settings.deploy_image_allow_remote,
                    images={
                        "mysql": self.settings.deploy_dependency_mysql_image,
                        "redis": self.settings.deploy_dependency_redis_image,
                        "postgres": self.settings.deploy_dependency_postgres_image,
                    },
                )
            result = self._dependency_manager.ensure(kind)
            self.dependency_env.update(self._dependency_manager.env)
            self.dependency_results.append(result)
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: {exc}"

    def write_dockerfile(self, content: str) -> str:
        text = str(content or "")
        if "FROM " not in text.upper():
            return "ERROR: Dockerfile 必须包含 FROM"
        if self.build_dir.exists():
            (self.build_dir / "Dockerfile").write_text(text, encoding="utf-8")
            self.plan["dockerfile"] = text[:4000]
            return f"OK: wrote {self.build_dir / 'Dockerfile'} ({len(text)} chars)"
        return "ERROR: 构建目录不存在"

    def _client(self):
        import docker

        return docker.from_env(timeout=max(300, int(self.settings.deploy_timeout_s) + 180))

    def docker_build(self) -> str:
        if not (self.build_dir / "Dockerfile").is_file():
            return "ERROR: 尚未 write_dockerfile"
        try:
            client = self._client()
            tag = f"codesentry-target-{self.scan_id}:agent"
            image, logs = client.images.build(
                path=str(self.build_dir), dockerfile="Dockerfile", tag=tag, rm=True,
                timeout=max(600, int(self.settings.deploy_timeout_s) * 3),
            )
            chunks = [str(c.get("stream")) for c in logs if isinstance(c, dict) and c.get("stream")]
            self.image = image.id
            self.build_log = "".join(chunks)[-3000:]
            return f"OK image={image.id[:12]}\n{self.build_log[-1500:]}"
        except Exception as exc:  # noqa: BLE001
            self.build_log = str(exc)[:3000]
            return f"ERROR: {str(exc)[:1500]}"

    def docker_run(self, port: int = 8080) -> str:
        if not self.image:
            return "ERROR: 尚未成功 docker_build"
        try:
            client = self._client()
            try:
                client.networks.get(self.network)
            except Exception:  # noqa: BLE001
                client.networks.create(
                    self.network, driver="bridge",
                    internal=self.settings.deploy_network_mode == "internal",
                )
            if self.settings.deploy_auto_dependencies and self._dependency_manager is None:
                detected = self.detect_dependencies()
                try:
                    for dep in json.loads(detected):
                        self.ensure_dependency(str(dep))
                except json.JSONDecodeError:
                    pass
            if self.container is not None:
                try:
                    self.container.remove(force=True)
                except Exception:  # noqa: BLE001, S110
                    pass
            container = client.containers.run(
                self.image,
                name=f"codesentry-target-{self.scan_id}",
                detach=True,
                network=self.network,
                ports={f"{int(port)}/tcp": ("127.0.0.1", None)},
                environment={**self.dependency_env, "SERVER_PORT": str(int(port))},
                mem_limit=f"{int(self.settings.deploy_mem_mb)}m",
                nano_cpus=int(float(self.settings.deploy_cpu) * 1_000_000_000),
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                labels={"codesentry.scan_id": str(self.scan_id), "codesentry.role": "target"},
            )
            self.container = container
            container.reload()
            ports = container.attrs.get("NetworkSettings", {}).get("Ports") or {}
            published = ports.get(f"{int(port)}/tcp") or []
            host_port = published[0].get("HostPort", "") if published else ""
            self.target_url = f"http://127.0.0.1:{host_port}/" if host_port else ""
            return f"OK container={container.id[:12]} target={self.target_url or '—'}"
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: {str(exc)[:1500]}"

    def docker_logs(self, tail: int = 80) -> str:
        if self.container is None:
            return "ERROR: 容器未启动"
        try:
            return self.container.logs(tail=int(tail)).decode("utf-8", "replace")[-4000:]
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: {exc}"

    def probe(self, url: str = "") -> str:
        target = url or self.target_url
        if not target:
            return "ERROR: 没有 target_url"
        import time

        import httpx

        last = ""
        for _ in range(10):
            try:
                response = httpx.get(target, timeout=3.0, follow_redirects=False)
                self.target_url = target
                self.status = "ready" if response.status_code < 500 else "degraded"
                return f"{response.status_code} {target}"
            except Exception as exc:  # noqa: BLE001
                last = str(exc)[:200]
                time.sleep(1.0)
        return f"ERROR: {last}"

    def finish(self, status: str, target_url: str = "", notes: str = "") -> str:
        self.status = status if status in ("ready", "degraded", "disabled") else "degraded"
        if target_url:
            self.target_url = target_url
        self.notes = notes
        self.plan["notes"] = notes
        return "OK"


def _java_images(raw: str) -> list[str]:
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        return []
    out = []
    for tag in rows if isinstance(rows, list) else []:
        low = str(tag).lower()
        if any(k in low for k in ("maven", "openjdk", "temurin", "jdk")) and "squid" not in low:
            out.append(str(tag))
    return out[:10]


def _plan_fallback(llm, session: DeploySession, build_files: dict,
                   previous_error: str = "") -> dict:
    """模型不走工具协议时的兜底：让 Agent 直接产出可执行部署方案。"""
    system = (
        "你是部署规划 Agent。只输出 JSON："
        '{"strategy":"dockerfile|maven|gradle|npm|pip|php|existing",'
        '"dockerfile":"完整的 Dockerfile 内容（strategy=dockerfile 时必填）",'
        '"port":8080,"notes":"一句话"}。'
        "Dockerfile 必须自包含构建步骤；不能依赖仓库里未构建的产物。"
    )
    payload = {
        "files": session.list_files(80),
        "build_files": build_files,
        "has_dockerfile": (session.build_dir / "Dockerfile").is_file(),
        "local_images": json.loads(session.local_images(60)),
        "java_images": _java_images(session.local_images(60)),
        "dependencies": session.detect_dependencies(),
        "previous_error": previous_error[-3000:],
    }
    try:
        text = llm.complete(system, json.dumps(payload, ensure_ascii=False)[:12000], model_role="deep")
    except Exception:  # noqa: BLE001
        return {}
    return _parse_final(text)


def _execute_plan(session: DeploySession, plan: dict) -> list[str]:
    steps: list[str] = []
    if plan.get("dockerfile"):
        session.write_dockerfile(str(plan["dockerfile"]))
        steps.append("write_dockerfile")
    if (session.build_dir / "Dockerfile").is_file():
        port = int(plan.get("port") or 8080)
        steps.append(session.docker_build()[:1200])
        if session.image:
            steps.append(session.docker_run(port)[:1200])
            if session.target_url:
                steps.append(session.probe()[:600])
    session.plan["execution"] = steps
    return steps


def run_deploy_agent(state: dict, runtime=None, llm=None) -> dict:
    from codesentry.config import get_settings
    from codesentry.sandbox.deploy import run_deploy

    settings = get_settings()
    if not settings.deploy_enabled:
        return {"deploy_status": "disabled", "deploy_log": "DEPLOY_ENABLED=false",
                "phase": "poc_gen"}
    if not int(state.get("scan_id") or 0) or not str(state.get("repo_path") or ""):
        return {"deploy_status": "disabled", "deploy_log": "缺少 scan_id/repo_path",
                "phase": "poc_gen"}

    session = DeploySession(state, settings)
    if runtime is not None:
        if not runtime.enabled:
            return {"deploy_status": "disabled", "deploy_log": "agent disabled",
                    "phase": "poc_gen"}
        llm = runtime.llm or llm
    if llm is None:
        fallback = run_deploy(state)
        fallback["deploy"] = {**(fallback.get("deploy") or {}), "strategy": "fallback"}
        return fallback

    system = runtime.system() if runtime is not None else SYSTEM
    if "write_dockerfile" not in system:
        system = system.rstrip() + "\n\n" + SYSTEM
    try:
        build_files = json.loads(session.inspect())
    except json.JSONDecodeError:
        build_files = {}
    user = json.dumps({
        "repo": str(session.root),
        "scan_id": session.scan_id,
        "network_mode": settings.deploy_network_mode,
        "timeout_s": settings.deploy_timeout_s,
        "files": json.loads(session.list_files(80)),
        "build_files": build_files,
        "local_images": json.loads(session.local_images(60)),
        "java_images": _java_images(session.local_images(60)),
        "dependencies": session.detect_dependencies(),
        "instruction": (
            "你已经看到仓库文件与构建文件。现在必须调用工具执行："
            "若已有可用 Dockerfile 可直接 docker_build；否则先 write_dockerfile。"
            "构建失败要读日志修正。不要在没有尝试工具的情况下直接返回 disabled。"
        ),
    }, ensure_ascii=False)[:16000]
    trace: list[dict] = []
    try:
        from codesentry.agents.tools import run_tool_loop

        max_iterations = int(getattr(runtime, "max_iterations", 8) or 8)
        text, trace = run_tool_loop(
            llm, system, user, tools=session.tools(),
            max_iterations=max_iterations, model_role="deep",
        )
        final = _parse_final(text)
        if final.get("status"):
            session.status = str(final["status"])
        if final.get("target_url"):
            session.target_url = str(final["target_url"])
        if final.get("notes"):
            session.notes = str(final["notes"])
    except Exception as exc:  # noqa: BLE001 - Agent 失败回退确定性配方
        fallback = run_deploy(state)
        fallback["deploy"] = {
            **(fallback.get("deploy") or {}),
            "strategy": "fallback",
            "agent_error": str(exc)[:200],
            "tool_trace": trace,
        }
        return fallback

    # 模型未调用工具时，让它给出可执行方案，再由沙箱执行
    if not session.image and session.container is None:
        plan = _plan_fallback(llm, session, build_files)
        if plan:
            session.plan.update(plan)
            steps = _execute_plan(session, plan)
            trace.append({"iteration": 1, "tool": "execute_plan", "output_preview": " | ".join(steps)[:500]})
        if not session.image:
            revision = _plan_fallback(llm, session, build_files, session.build_log)
            if revision:
                session.plan.update(revision)
                steps = _execute_plan(session, revision)
                trace.append({"iteration": 2, "tool": "revise_plan", "output_preview": " | ".join(steps)[:500]})

    status = session.status
    if not status:
        status = "ready" if session.target_url else ("degraded" if session.image else "disabled")
    log = session.notes or ""
    if session.build_log:
        log = f"{log}\nbuild: {session.build_log[-1000:]}".strip()
    return {
        "deploy_status": status,
        "deploy_log": log[:4000],
        "target_url": session.target_url,
        "deploy": {
            "status": status,
            "target_url": session.target_url,
            "container_id": (session.container.id[:12] if session.container else ""),
            "network": "host-loopback",
            "strategy": "agent",
            "plan": session.plan,
            "tool_trace": trace,
        },
        "phase": "poc_gen",
    }
