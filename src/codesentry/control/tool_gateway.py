"""外部安全工具网关：固定 argv、白名单、证据归一化。"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

TOOLS: dict[str, dict[str, Any]] = {
    "gitleaks": {
        "bin": "gitleaks", "network": False,
        "argv": ["detect", "--source", ".", "--no-git", "--report-format", "json",
                 "--report-path", "-"],
        "kind": "secret",
    },
    "bandit": {
        "bin": "bandit", "network": False,
        "argv": ["-r", ".", "-f", "json", "-q"], "kind": "sast",
    },
    "osv": {
        "bin": "osv-scanner", "network": True,
        "argv": ["--format", "json", "-r", "."], "kind": "dependency",
    },
    "npm_audit": {
        "bin": "npm", "network": True,
        "argv": ["audit", "--json"], "kind": "dependency",
        "requires": "package.json",
    },
    "safety": {
        "bin": "safety", "network": True,
        "argv": ["check", "--json"], "kind": "dependency",
        "requires": "requirements.txt",
    },
}


def list_tools() -> list[dict]:
    from codesentry.config import get_settings

    allow_network = get_settings().tool_allow_network
    out = []
    for name, spec in TOOLS.items():
        binary = shutil.which(str(spec["bin"])) or ""
        out.append({"name": name, "kind": spec["kind"],
                    "network": spec["network"], "network_enabled": allow_network,
                    "binary": binary, "available": bool(binary)})
    return out


def _items(payload) -> list:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("findings", "results", "vulnerabilities", "issues", "matches"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [{"key": k, **v} for k, v in value.items() if isinstance(v, dict)]
    return []


def run_tool(scan_id: int, name: str, repo: str, *, allow_network: bool = False,
             timeout_s: int = 300) -> dict:
    spec = TOOLS.get(name)
    if not spec:
        raise ValueError(f"unknown tool: {name}")
    root = Path(repo).resolve()
    if not root.is_dir():
        raise ValueError("repo not found")
    if spec.get("requires") and not (root / str(spec["requires"])).is_file():
        return {"status": "unavailable", "tool": name,
                "reason": f"missing {spec['requires']}", "items": []}
    if spec["network"] and not allow_network:
        return {"status": "unavailable", "tool": name,
                "reason": "network tools disabled", "items": []}
    binary = shutil.which(str(spec["bin"]))
    if not binary:
        return {"status": "unavailable", "tool": name,
                "reason": f"binary not found: {spec['bin']}", "items": []}
    env = {"HTTP_PROXY": "", "HTTPS_PROXY": "", "http_proxy": "", "https_proxy": "",
           "NO_PROXY": "*", "no_proxy": "*"}
    start = time.time()
    try:
        proc = subprocess.run([binary, *[str(x) for x in spec["argv"]]], cwd=str(root), env=env,
                              capture_output=True, text=True, timeout=timeout_s,
                              check=False)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "tool": name, "reason": "timeout", "items": []}
    duration = int((time.time() - start) * 1000)
    raw = proc.stdout or ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {"raw": raw[:4000]}
    items = _items(payload)[:200]
    status = "ok" if proc.returncode in (0, 1) else "error"
    evidence = items[:20]
    result = {"status": status, "tool": name, "items": items,
              "count": len(items), "exit_code": proc.returncode,
              "stderr": (proc.stderr or "")[:1000], "duration_ms": duration,
              "evidence": evidence}
    _save(scan_id, name, spec, result)
    try:
        from codesentry.orchestrator.events import publish_event

        publish_event(scan_id, "tool.result", agent="tool", phase="tools",
                      payload={"tool": name, "status": status, "count": len(items)})
    except Exception:  # noqa: BLE001, S110
        pass
    return result


def _save(scan_id: int, name: str, spec: dict, result: dict) -> None:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tool_runs (scan_id, tool, status, args, result, evidence,"
                " duration_ms) VALUES (%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s)",
                (int(scan_id), name, result["status"],
                 json.dumps({"argv": spec["argv"]}),
                 json.dumps({k: result[k] for k in ("count", "exit_code", "stderr",
                                                    "duration_ms")}),
                 json.dumps(result.get("evidence") or []),
                 int(result.get("duration_ms") or 0)),
            )
            conn.commit()
    except Exception:  # noqa: BLE001, S110
        pass


def list_runs(scan_id: int, limit: int = 50) -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, tool, status, result, evidence, duration_ms, created_at"
                " FROM tool_runs WHERE scan_id=%s ORDER BY id DESC LIMIT %s",
                (int(scan_id), max(1, min(int(limit), 200))),
            )
            rows = cur.fetchall()
        return [{"id": r[0], "tool": r[1], "status": r[2], "result": r[3],
                 "evidence": r[4], "duration_ms": r[5], "created_at": str(r[6])}
                for r in rows]
    except Exception:  # noqa: BLE001
        return []
