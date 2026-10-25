from types import SimpleNamespace

from codesentry.sandbox.deploy import (
    RECIPES,
    detect_runtime_dependencies,
    ensure_image,
)


class _Images:
    def __init__(self, existing: bool):
        self.existing = existing
        self.pulled: list[str] = []

    def get(self, image: str):
        if not self.existing:
            raise RuntimeError("ImageNotFound")
        return object()

    def pull(self, image: str):
        self.pulled.append(image)
        return object()


def test_ensure_image_never_does_not_pull():
    images = _Images(False)
    client = SimpleNamespace(images=images)
    assert ensure_image(client, "x:1", "never") is False
    assert images.pulled == []


def test_ensure_image_missing_pulls_only_when_absent():
    missing = _Images(False)
    assert ensure_image(SimpleNamespace(images=missing), "x:1", "missing") is True
    assert missing.pulled == ["x:1"]
    present = _Images(True)
    assert ensure_image(SimpleNamespace(images=present), "x:1", "missing") is True
    assert present.pulled == []


def test_ensure_image_always_pulls():
    images = _Images(True)
    assert ensure_image(SimpleNamespace(images=images), "x:1", "always") is True
    assert images.pulled == ["x:1"]


def test_maven_command_handles_jar_and_war():
    command = RECIPES["maven"]["command"]
    assert "-jar" in command
    assert "JAVA_NOT_FOUND" in command
    assert "*.war" in command
    assert "WAR_PACKAGING_REQUIRES_TOMCAT" in command


def test_detect_runtime_dependencies(tmp_path):
    res = tmp_path / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application-dev.yml").write_text(
        "spring:\n  datasource:\n    url: jdbc:mysql://localhost/db\n"
        "  redis:\n    host: localhost\n",
        encoding="utf-8",
    )
    deps = detect_runtime_dependencies(tmp_path)
    assert "MySQL" in deps
    assert "Redis" in deps
