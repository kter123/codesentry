"""部署依赖编排（P2）：按需启动 MySQL/Redis/PostgreSQL 并注入 env。"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, cast

DEPENDENCIES = {
    "mysql": {
        "image": "mysql:8.0",
        "env": {
            "MYSQL_ROOT_PASSWORD": "root",
            "MYSQL_DATABASE": "codesentry",
            "MYSQL_USER": "codesentry",
            "MYSQL_PASSWORD": "codesentry",
        },
        "port": 3306,
        "health": ["mysqladmin", "ping", "-h", "127.0.0.1", "-uroot", "-proot"],
    },
    "redis": {
        "image": "redis:7-alpine",
        "env": {},
        "port": 6379,
        "health": ["redis-cli", "ping"],
    },
    "postgres": {
        "image": "postgres:16-alpine",
        "env": {
            "POSTGRES_DB": "codesentry",
            "POSTGRES_USER": "codesentry",
            "POSTGRES_PASSWORD": "codesentry",
        },
        "port": 5432,
        "health": ["pg_isready", "-U", "codesentry"],
    },
}

_ENV_KEYS = {
    "mysql": {
        "host": "MYSQL_HOST", "port": "MYSQL_PORT", "user": "MYSQL_USERNAME",
        "password": "MYSQL_PASSWORD", "database": "MYSQL_DATABASE",
    },
    "redis": {"host": "REDIS_HOST", "port": "REDIS_PORT"},
    "postgres": {
        "host": "POSTGRES_HOST", "port": "POSTGRES_PORT",
        "user": "POSTGRES_USER", "password": "POSTGRES_PASSWORD",
        "database": "POSTGRES_DB",
    },
}


def _db_name(root: Path, kind: str) -> str:
    try:
        text = "\n".join(
            p.read_text(errors="replace")[:20000]
            for pattern in ("application*.yml", "application*.yaml", "application*.properties")
            for p in root.rglob(pattern)
        )
    except Exception:  # noqa: BLE001
        return "codesentry"
    if kind == "mysql":
        m = re.search(r"jdbc:mysql://[^/\s\"']+/([A-Za-z0-9_]+)", text)
        return m.group(1) if m else "codesentry"
    if kind == "postgres":
        m = re.search(r"jdbc:postgresql://[^/\s\"']+/([A-Za-z0-9_]+)", text)
        return m.group(1) if m else "codesentry"
    return "codesentry"


class DependencyManager:
    def __init__(self, client, network: str, scan_id: int, *, root: Path,
                 timeout_s: int = 90, pull_policy: str = "missing",
                 allow_remote: bool = False,
                 images: dict[str, str] | None = None) -> None:
        from codesentry.sandbox.deploy import ensure_image

        self.client = client
        self.network = network
        self.scan_id = int(scan_id)
        self.root = root
        self.timeout_s = max(15, int(timeout_s))
        self.pull_policy = pull_policy
        self.allow_remote = allow_remote
        self.images = dict(images or {})
        self._ensure_image = ensure_image
        self.started: list[dict] = []
        self.env: dict[str, str] = {}
        self.notes: list[str] = []

    @staticmethod
    def detect(root: Path) -> list[str]:
        from codesentry.sandbox.deploy import detect_runtime_dependencies

        found = []
        for name in detect_runtime_dependencies(root):
            low = name.lower()
            if low == "postgresql":
                low = "postgres"
            if low in DEPENDENCIES:
                found.append(low)
        return found

    def _name(self, kind: str) -> str:
        return f"codesentry-dep-{self.scan_id}-{kind}"

    def _existing(self, kind: str):
        try:
            c = self.client.containers.get(self._name(kind))
            c.reload()
            return c
        except Exception:  # noqa: BLE001
            return None

    def _health(self, container, kind: str) -> bool:
        cmd = cast(dict[str, Any], DEPENDENCIES[kind])["health"]
        deadline = time.time() + self.timeout_s
        while time.time() < deadline:
            try:
                r = container.exec_run(cmd, demux=False)
                if r.exit_code == 0:
                    return True
            except Exception:  # noqa: BLE001, S110
                pass
            time.sleep(1.0)
        return False

    def ensure(self, kind: str) -> dict:
        kind = kind.lower()
        if kind not in DEPENDENCIES:
            return {"kind": kind, "ok": False, "error": "unsupported dependency"}
        existing = self._existing(kind)
        if existing is not None and existing.status == "running":
            self._inject_env(kind, self._name(kind))
            return {"kind": kind, "ok": True, "reused": True,
                    "container": existing.name}
        spec = cast(dict[str, Any], DEPENDENCIES[kind])
        image = self.images.get(kind) or str(spec["image"])
        if not self.allow_remote and self.pull_policy != "never":
            # 远程关闭时只允许本地镜像
            local_ok = True
            try:
                self.client.images.get(image)
            except Exception:  # noqa: BLE001
                local_ok = False
            if not local_ok:
                self.notes.append(f"{kind} 镜像 {image} 不在本地，且未允许远程拉取")
                return {"kind": kind, "ok": False, "image": image,
                        "error": "image not local and remote disabled"}
        try:
            if not self._ensure_image(self.client, image, self.pull_policy):
                self.notes.append(f"{kind} 镜像 {image} 缺失（pull={self.pull_policy}）")
                return {"kind": kind, "ok": False, "image": image,
                        "error": "image missing"}
            env: dict[str, str] = {str(k): str(v) for k, v in (spec.get("env") or {}).items()}
            if kind == "mysql":
                env["MYSQL_DATABASE"] = _db_name(self.root, "mysql")
            elif kind == "postgres":
                env["POSTGRES_DB"] = _db_name(self.root, "postgres")
            container = self.client.containers.run(
                image,
                name=self._name(kind),
                detach=True,
                network=self.network,
                network_aliases=[kind],
                environment=env,
                mem_limit="256m",
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                labels={"codesentry.scan_id": str(self.scan_id),
                        "codesentry.role": "dependency", "codesentry.kind": kind},
                auto_remove=False,
            )
            self.started.append({"kind": kind, "container": container.name,
                                 "image": image})
            healthy = self._health(container, kind)
            if not healthy:
                return {"kind": kind, "ok": False, "image": image,
                        "container": container.name, "error": "health timeout"}
            self._inject_env(kind, self._name(kind))
            return {"kind": kind, "ok": True, "image": image,
                    "container": container.name}
        except Exception as e:  # noqa: BLE001
            self.notes.append(f"{kind} 启动失败：{str(e)[:200]}")
            return {"kind": kind, "ok": False, "image": image,
                    "error": str(e)[:200]}

    def _inject_env(self, kind: str, host: str) -> None:
        keys = _ENV_KEYS[kind]
        port = str(DEPENDENCIES[kind]["port"])
        self.env[keys["host"]] = host
        self.env[keys["port"]] = port
        if kind == "mysql":
            self.env[keys["user"]] = "root"
            self.env[keys["password"]] = "root"
            self.env[keys["database"]] = _db_name(self.root, "mysql")
        elif kind == "postgres":
            self.env[keys["user"]] = "codesentry"
            self.env[keys["password"]] = "codesentry"
            self.env[keys["database"]] = _db_name(self.root, "postgres")

    def ensure_all(self, kinds: list[str] | None = None) -> list[dict]:
        return [self.ensure(k) for k in (kinds or self.detect(self.root))]

    def cleanup(self) -> None:
        for row in self.started:
            try:
                c = self.client.containers.get(row["container"])
                c.stop(timeout=3)
                c.remove(force=True)
            except Exception:  # noqa: BLE001, S110
                pass
        self.started.clear()
