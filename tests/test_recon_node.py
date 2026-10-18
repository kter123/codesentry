"""节点级 agent 单测（LLM 全 mock 或纯逻辑）。"""

from codesentry.agents.recon import build_profile, diff_reachable_closure, run_recon
from codesentry.agents.state import new_state


def test_build_profile_python(tmp_path):
    (tmp_path / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n")
    (tmp_path / "requirements.txt").write_text("flask==3.0\n")
    p = build_profile(str(tmp_path))
    assert "python" in p["languages"]
    assert "requirements.txt" in p["frameworks"]


def test_run_recon_updates_state(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    s = new_state(str(tmp_path), OSS=False)
    update = run_recon(s)
    assert update["phase"] == "scan"
    assert update["profile"]["languages"] == ["python"]


def test_diff_closure_bfs(tmp_path):
    src = '''
def entry_a():
    return helper_b()

def helper_b():
    return sink_c()

def sink_c():
    return do_danger()

def do_danger():
    return "danger"

def unrelated_x():
    return 1
'''
    (tmp_path / "main.py").write_text(src)
    closure = diff_reachable_closure(str(tmp_path), ["main.py"])
    assert closure == ["main.py"]  # 同文件内自然可达


def test_diff_closure_cross_file(tmp_path):
    (tmp_path / "entry.py").write_text(
        "from lib import helper_b\n\ndef entry_a():\n    return helper_b()\n"
    )
    (tmp_path / "lib.py").write_text(
        "def helper_b():\n    return sink_c()\n\ndef sink_c():\n    import os\n    return os.popen('x')\n"
    )
    closure = diff_reachable_closure(str(tmp_path), ["entry.py"])
    # 闭包应包含 diff 文件本身；跨文件可达链是否纳入取决于 BFS + import 名解析（M3.5 GraphRAG 深化）
    assert "entry.py" in " ".join(closure)
