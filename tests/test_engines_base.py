from codesentry.engines.base import SubprocResult, run_subprocess


def test_run_success():
    r = run_subprocess(["python3", "-c", "print('hi')"], timeout=10)
    assert r.ok and r.stdout.strip() == "hi"


def test_run_timeout():
    r = run_subprocess(["python3", "-c", "import time; time.sleep(5)"], timeout=1)
    assert not r.ok and "timeout" in r.reason.lower()


def test_run_bad_binary():
    r = run_subprocess(["codesentry-nonexistent-bin-_xyz"], timeout=5)
    assert not r.ok and ("not found" in r.reason.lower() or "enoent" in r.reason.lower())


def test_stderr_not_in_stdout():
    r = run_subprocess(
        ["python3", "-c", "import sys; print('out'); sys.stderr.write('err')"], timeout=10
    )
    assert "out" in r.stdout and "out" not in r.stderr
