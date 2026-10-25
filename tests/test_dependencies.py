from types import SimpleNamespace

from codesentry.sandbox import dependencies


class _Images:
    def __init__(self, exists=True):
        self.exists = exists

    def get(self, image):
        if not self.exists:
            raise RuntimeError("missing")
        return object()


class _Container:
    def __init__(self, name):
        self.name = name
        self.status = "running"
        self.id = "cid"
        self.attrs = {}

    def reload(self):
        return None

    def exec_run(self, cmd, demux=False):
        return SimpleNamespace(exit_code=0, output=b"ok")

    def stop(self, timeout=3):
        return None

    def remove(self, force=True):
        return None


class _Containers:
    def __init__(self):
        self.created = []
        self.by_name = {}

    def get(self, name):
        if name in self.by_name:
            return self.by_name[name]
        raise RuntimeError("not found")

    def run(self, image, **kwargs):
        c = _Container(kwargs.get("name", "c"))
        self.created.append((image, kwargs, c))
        self.by_name[c.name] = c
        return c


def _client(images_exists=True):
    return SimpleNamespace(images=_Images(images_exists), containers=_Containers())


def test_detect_dependencies(tmp_path):
    res = tmp_path / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.yml").write_text(
        "spring:\n  datasource:\n    url: jdbc:mysql://db:3306/kvf_admin\n"
        "  redis:\n    host: redis\n  jdbc: postgresql://pg:5432/app\n",
        encoding="utf-8",
    )
    assert set(dependencies.DependencyManager.detect(tmp_path)) == {"mysql", "redis", "postgres"}


def test_ensure_starts_dependency_and_injects_env(tmp_path, monkeypatch):
    res = tmp_path / "src"
    res.mkdir()
    (res / "application.yml").write_text(
        "url: jdbc:mysql://db:3306/kvf_admin\n", encoding="utf-8"
    )
    client = _client(True)
    monkeypatch.setattr("codesentry.sandbox.deploy.ensure_image",
                        lambda c, i, p="missing": True)
    mgr = dependencies.DependencyManager(
        client, "net", 1, root=tmp_path, pull_policy="never", allow_remote=False,
        images={"mysql": "local/mysql:8"},
    )
    out = mgr.ensure("mysql")
    assert out["ok"] is True
    assert mgr.env["MYSQL_HOST"] == "codesentry-dep-1-mysql"
    assert mgr.env["MYSQL_DATABASE"] == "kvf_admin"
    assert mgr.env["MYSQL_USERNAME"] == "root"
    assert client.containers.created[0][1]["network_aliases"] == ["mysql"]
    mgr.cleanup()
    assert client.containers.created[0][2].name in client.containers.by_name


def test_never_policy_missing_image_does_not_start(tmp_path, monkeypatch):
    client = _client(False)
    monkeypatch.setattr("codesentry.sandbox.deploy.ensure_image",
                        lambda c, i, p="missing": False)
    mgr = dependencies.DependencyManager(
        client, "net", 2, root=tmp_path, pull_policy="never", allow_remote=False,
    )
    out = mgr.ensure("redis")
    assert out["ok"] is False
    assert "image" in out["error"] or "镜像" in " ".join(mgr.notes)
    assert not client.containers.created


def test_ensure_is_idempotent(tmp_path, monkeypatch):
    client = _client(True)
    monkeypatch.setattr("codesentry.sandbox.deploy.ensure_image",
                        lambda c, i, p="missing": True)
    mgr = dependencies.DependencyManager(
        client, "net", 3, root=tmp_path, pull_policy="never", allow_remote=False,
    )
    first = mgr.ensure("redis")
    second = mgr.ensure("redis")
    assert first["ok"] and second["ok"] and second.get("reused") is True
    assert len(client.containers.created) == 1
