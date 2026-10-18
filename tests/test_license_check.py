import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_licenses.py"


def _git_commit_all(repo: Path):
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "x", "--allow-empty"],
        cwd=repo, check=True, capture_output=True,
    )


def _run(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT)], cwd=repo, capture_output=True, text=True)


def test_clean_repo_passes(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "src.py").write_text("print('hi')")
    _git_commit_all(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "passed" in r.stdout


def test_ql_file_violates(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "evil.ql").write_text("select 1")
    _git_commit_all(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "evil.ql" in r.stdout + r.stderr


def test_semgrep_rules_dir_violates(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    rules = tmp_path / "semgrep-rules"
    rules.mkdir()
    (rules / "r.yml").write_text("rules: []")
    _git_commit_all(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 1


def test_import_codeql_txt_violates(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "x.py").write_text("import codeql  # bad")
    _git_commit_all(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 1
