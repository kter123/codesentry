"""diff 命令：git diff → 变更文件表 → 可达闭包 → 走 graph（mode=diff）→ 报告/SARIF/退出码（FR-10）。"""

import subprocess


def changed_files(repo: str, base: str, head: str) -> list[str]:
    r = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        cwd=repo, capture_output=True, text=True, check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"git diff 失败：{r.stderr[:200]}")
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]
