
from codesentry.control import harness


class _LLM:
    def complete(self, *a, **k):
        return ('{"language":"python","code":"print(\\"HARNESS_VERIFIED\\")",'
                '"summary":"mock check","payloads":["x"]}')


class _Container:
    def wait(self, timeout=None):
        return {"StatusCode": 0}

    def logs(self, stdout=True, stderr=False):
        return b"HARNESS_VERIFIED\n"

    def kill(self):
        return None

    def remove(self, force=True):
        return None


class _Client:
    class containers:
        @staticmethod
        def run(*a, **k):
            return _Container()

    class images:
        @staticmethod
        def get(image):
            return object()


def test_parse_harness_output():
    assert harness.parse_harness_output("x HARNESS_VERIFIED")[0] == "verified"
    assert harness.parse_harness_output("HARNESS_NOT_TRIGGERED")[0] == "rejected"
    assert harness.parse_harness_output("boom")[0] == "environment_error"


def test_generate_harness():
    out = harness.generate_harness(_LLM(), {"cwe": 78}, "1: os.system(cmd)")
    assert out["language"] == "python"
    assert "HARNESS_VERIFIED" in out["code"]
    assert out["summary"] == "mock check"


def test_run_harness_verified(monkeypatch):
    monkeypatch.setattr("docker.DockerClient.from_env", lambda **k: _Client())
    monkeypatch.setattr("codesentry.sandbox.deploy.ensure_image",
                        lambda c, i, p="missing": True)
    out = harness.run_harness("print('HARNESS_VERIFIED')", "python",
                              image="x", pull_policy="never")
    assert out["verdict"] == "verified"
    assert out["status"] == "ok"
    assert out["exit_code"] == 0


def test_run_harness_environment_error(monkeypatch):
    monkeypatch.setattr("docker.DockerClient.from_env", lambda **k: _Client())
    monkeypatch.setattr("codesentry.sandbox.deploy.ensure_image",
                        lambda c, i, p="missing": False)
    out = harness.run_harness("print(1)", "python", image="missing", pull_policy="never")
    assert out["status"] == "environment_error"
    assert out["verdict"] == "plausible"
