"""扫描仓库中的疑似密钥（CI 可用）。发现即 exit 1。"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

PATTERNS = [
    re.compile(r"oc_sk_[A-Za-z0-9_-]{16,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]
SKIP_DIRS = {".git", ".venv", "node_modules", "work", "__pycache__", ".pytest_cache"}


def main() -> int:
    try:
        files = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.split()
    except Exception:  # noqa: BLE001
        files = [str(p) for p in Path(".").rglob("*") if p.is_file()]
    hits: list[tuple[str, int, str]] = []
    for name in files:
        p = Path(name)
        if any(part in SKIP_DIRS for part in p.parts) or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for pat in PATTERNS:
                if pat.search(line):
                    hits.append((name, i, pat.pattern))
    for name, line, pattern in hits:
        print(f"{name}:{line}: matched {pattern}")
    if hits:
        print(f"FAILED: {len(hits)} suspicious secret(s)")
        return 1
    print("OK: no suspicious secrets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
