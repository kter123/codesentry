from codesentry.sandbox import deploy


def test_choose_java_image_precedence(monkeypatch):
    monkeypatch.setattr(deploy, "local_java_image", lambda: "local/maven:8")
    assert deploy.choose_java_image("explicit:8") == "explicit:8"
    assert deploy.choose_java_image("") == "local/maven:8"
    monkeypatch.setattr(deploy, "local_java_image", lambda: None)
    assert deploy.choose_java_image("") is None
    assert deploy.choose_java_image("", allow_remote=True) == "maven:3.9-eclipse-temurin-8"


def test_deploy_image_config_fields():
    from codesentry.config import Settings

    s = Settings(_env_file=None)
    assert s.deploy_image_pull in ("never", "missing", "always")
    assert s.deploy_java_image == ""
    assert s.deploy_image_allow_remote is False
