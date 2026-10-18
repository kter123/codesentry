"""引擎子进程公共封装（agent.md §10：超时不挂死、stdout/stderr 分离）。"""

import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class SubprocResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    reason: str = ""
    exit_code: int | None = None


def run_subprocess(cmd: list[str], timeout: int, cwd: str | None = None) -> SubprocResult:
    if shutil.which(cmd[0]) is None:
        return SubprocResult(ok=False, reason=f"binary not found: {cmd[0]}")
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False, cwd=cwd
        )
    except subprocess.TimeoutExpired:
        return SubprocResult(ok=False, reason=f"timeout after {timeout}s")
    except OSError as e:
        return SubprocResult(ok=False, reason=f"os error: {e}")
    return SubprocResult(
        ok=r.returncode == 0,
        stdout=r.stdout or "",
        stderr=r.stderr or "",
        reason="" if r.returncode == 0 else f"exit code {r.returncode}",
        exit_code=r.returncode,
    )
