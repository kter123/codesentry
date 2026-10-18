#!/usr/bin/env python3
"""CodeSentry license red-line check (agent.md §3).

Exits: 0 = passed, 1 = violations found, 2 = not a git repo.
Standard library only — must run outside the project venv.
"""

import fnmatch
import subprocess
import sys
from pathlib import Path

TEXT_LIMIT_BYTES = 1_000_000
SKIP_PATTERNS = ("check_licenses.py",)
DOC_DIRS = ("doc/", "tests/")


def _ls_files(repo: Path) -> list[str]:
    r = subprocess.run(["git", "ls-files"], check=False, cwd=repo, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"error: not a git repository: {repo}", file=sys.stderr)
        sys.exit(2)
    return [line for line in r.stdout.splitlines() if line.strip()]


# CodeQL 检测/解析适配器（fr-3 gate + SARIF 解析，agent.md 明确允许「仅探测用户自装二进制」）
CODEQL_ADAPTER_ALLOW = ("src/codesentry/engines/codeql.py", "tests/", "doc/", "rules/")


def check_codeql_absence(files: list[str], repo: Path) -> list[str]:
    violations = []
    for path in files:
        name = path.rsplit("/", 1)[-1]
        matched = next(
            (
                pat
                for pat in ("*.ql", "*.qll", "codeql*")
                if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(path.lower(), f"*/{pat}")
            ),
            None,
        )
        if matched and not any(path.startswith(p.rstrip("/")) for p in CODEQL_ADAPTER_ALLOW):
            violations.append(
                f"{path}: CodeQL artifact found (red line: no CodeQL in distribution)"
            )
            continue
        full = repo / path
        if matched and any(path.startswith(p.rstrip("/")) for p in CODEQL_ADAPTER_ALLOW):
            full = repo / path  # 适配器文件仍走文本扫描（内容须无 SDK import）
        try:
            data = full.read_bytes()
        except OSError:
            continue
        if len(data) < TEXT_LIMIT_BYTES:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if ("import codeql" in text or "from codeql" in text) and not any(
                path.startswith(d) for d in DOC_DIRS
            ):
                violations.append(
                    f"{path}: 'import codeql' found (red line: CodeQL SDK import)"
                )
    return violations


def check_semgrep_rules_absence(files: list[str]) -> list[str]:
    return [
        f"{path}: official semgrep rules found (red line: rules not bundled)"
        for path in files
        if "/semgrep-rules/" in f"/{path}/"
        or path.startswith("semgrep-rules/")
        or "/semgrep-rules/" in f"/{path}"
    ]


def main() -> int:
    repo = Path.cwd()
    files = _ls_files(repo)
    files = [f for f in files if not any(p in f for p in SKIP_PATTERNS)]
    violations = check_codeql_absence(files, repo) + check_semgrep_rules_absence(files)
    for v in violations:
        print(f"[violation] {v}")
    if violations:
        return 1
    print("license check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
