"""Harness 验证（Fusion Phase 1）：LLM 生成测试代码 → Docker 沙箱执行。"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

HARNESS_SYSTEM = """你是 CodeSentry 的漏洞验证 Agent。给定 finding、源码和代码图路径，
写一个**最小、自包含**的 Fuzzing Harness，在 Docker 沙箱里验证漏洞是否真实触发。

要求：
1. 只输出 JSON：{"language":"python|javascript|php|ruby|java|go|bash",
   "code":"完整可执行代码","summary":"验证思路","payloads":["..."]}。
2. 代码必须自己 mock 依赖（数据库、HTTP、文件系统、命令执行），不要依赖目标项目能启动。
3. 触发漏洞时打印 `HARNESS_VERIFIED`；未触发打印 `HARNESS_NOT_TRIGGERED`。
4. 不要执行破坏性命令，不要访问网络，不要反弹 shell、交互 shell、提权。
5. 不要修改项目源码。
6. 证据不足时输出 code 为空字符串并说明原因。
"""


def _language(s: str) -> str:
    value = str(s or "python").lower()
    return value if value in ("python", "javascript", "php", "ruby", "java", "go", "bash") else "python"


def _command(language: str) -> str:
    ext = {
        "python": ".py", "javascript": ".js", "php": ".php", "ruby": ".rb",
        "java": "Harness.java", "go": ".go", "bash": ".sh",
    }[language]
    path = f"/tmp/harness{ext}" if language != "java" else "/tmp/Harness.java"
    runners = {
        "python": f"python3 {path}",
        "javascript": f"node {path}",
        "php": f"php {path}",
        "ruby": f"ruby {path}",
        "java": f"java {path}",
        "go": f"go run {path}",
        "bash": f"bash {path}",
    }
    return f"""sh -lc 'printf "%s" "$HARNESS_CODE" > {path}; {runners[language]}'"""


def parse_harness_output(text: str) -> tuple[str, str]:
    value = str(text or "")
    if "HARNESS_VERIFIED" in value:
        return "verified", "harness 输出 HARNESS_VERIFIED"
    if "HARNESS_NOT_TRIGGERED" in value:
        return "rejected", "harness 已执行但未触发"
    return "environment_error", "harness 未给出明确触发标记"


def run_harness(code: str, language: str, *, image: str = "",
                timeout_s: int = 90, allow_network: bool = False,
                pull_policy: str = "missing") -> dict:
    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.sandbox.deploy import ensure_image

    ensure_control_schema()
    image = image or "python:3.12-slim"
    start = time.time()
    try:
        import docker

        client = docker.from_env(timeout=max(120, timeout_s + 60))
        if not ensure_image(client, image, pull_policy):
            return {"status": "environment_error", "verdict": "plausible",
                    "exit_code": None, "stdout": "", "stderr": f"镜像不可用：{image}",
                    "duration_ms": int((time.time() - start) * 1000)}
        container = client.containers.run(
            image,
            command=_command(_language(language)),
            detach=True,
            environment={"HARNESS_CODE": code},
            network_mode="bridge" if allow_network else "none",
            read_only=True,
            mem_limit="512m",
            nano_cpus=500_000_000,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            tmpfs={"/tmp": "rw,size=100m,mode=1777"},
            working_dir="/tmp",
            auto_remove=False,
            labels={"codesentry.role": "harness"},
        )
        try:
            result = container.wait(timeout=timeout_s)
            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", "replace")[:8000]
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", "replace")[:4000]
            exit_code = int(result.get("StatusCode", -1))
        except Exception as e:  # noqa: BLE001 - 超时也尽力取日志
            try:
                container.kill()
            except Exception:  # noqa: BLE001, S110
                pass
            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", "replace")[:8000]
            stderr = str(e)[:2000]
            exit_code = -1
        finally:
            try:
                container.remove(force=True)
            except Exception:  # noqa: BLE001, S110
                pass
        verdict, reason = parse_harness_output(stdout + "\n" + stderr)
        if exit_code != 0 and verdict == "environment_error":
            status = "error"
            verdict = "plausible"
        else:
            status = "ok" if verdict != "environment_error" else "error"
        return {"status": status, "verdict": verdict, "exit_code": exit_code,
                "stdout": stdout, "stderr": stderr, "reason": reason,
                "duration_ms": int((time.time() - start) * 1000)}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "verdict": "plausible", "exit_code": None,
                "stdout": "", "stderr": str(e)[:500],
                "reason": "沙箱执行失败", "duration_ms": int((time.time() - start) * 1000)}


def generate_harness(llm, finding: dict, source: str, graph: dict | None = None) -> dict:
    from codesentry.control.harness_templates import for_cwe

    template = for_cwe(int(finding.get("cwe") or 0))
    user = json.dumps({"finding": finding, "source": source[:16000],
                       "graph": graph or {}, "template": template},
                      ensure_ascii=False)[:20000]
    text = llm.complete(HARNESS_SYSTEM, user, model_role="deep")
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("LLM 未返回 Harness JSON")
    data = json.loads(match.group(0))
    code: str = str(data.get("code") or "")
    if not code.strip():
        raise ValueError(str(data.get("summary") or "LLM 未生成 Harness 代码"))
    return {"language": _language(data.get("language")),
            "code": code[:30000], "summary": str(data.get("summary") or "")[:1000],
            "payloads": data.get("payloads") or []}


def extract_function(project: str, file: str, line: int, function: str = "") -> dict:
    from pathlib import Path

    from codesentry.rag.graph_query import node, node_for_location

    key = ""
    if function:
        found = node(project, function)
        key = str(found.get("key") or "") if found else ""
    if not key:
        key = node_for_location(project, file, int(line or 0)) or ""
    found = node(project, key) if key else None
    if not found:
        return {"ok": False, "error": "function not found", "file": file, "line": line}
    root = Path(project)
    try:
        lines = (root / found["path"]).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        return {"ok": False, "error": str(e), "node": found}
    start = max(1, int(found.get("start") or 1))
    end = min(len(lines), int(found.get("end") or start + 120))
    return {"ok": True, "node": found,
            "source": "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))[:24000]}


def save_run(scan_id: int, finding_id: int | None, path_id: int | None,
             cwe: int, language: str, code: str, result: dict,
             evidence: dict | None = None) -> int | None:
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO verification_runs (scan_id, finding_id, path_id, cwe, language,"
                " harness_code, status, verdict, exit_code, stdout, stderr, evidence,"
                " duration_ms) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)"
                " RETURNING id",
                (int(scan_id), finding_id, path_id, int(cwe or 0), language, code,
                 result.get("status") or "error", result.get("verdict") or "plausible",
                 result.get("exit_code"), result.get("stdout") or "",
                 result.get("stderr") or "", json.dumps(evidence or {}),
                 int(result.get("duration_ms") or 0)),
            )
            rid = int(cur.fetchone()[0])
            conn.commit()
        return rid
    except Exception:  # noqa: BLE001
        return None


def list_runs(scan_id: int, finding_id: int | None = None, limit: int = 50) -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        sql = ("SELECT id, finding_id, path_id, cwe, language, status, verdict, exit_code,"
               " stdout, stderr, evidence, duration_ms, created_at FROM verification_runs"
               " WHERE scan_id=%s")
        params: list = [int(scan_id)]
        if finding_id is not None:
            sql += " AND finding_id=%s"
            params.append(int(finding_id))
        sql += " ORDER BY id DESC LIMIT %s"
        params.append(max(1, min(int(limit), 200)))
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        keys = ["id", "finding_id", "path_id", "cwe", "language", "status", "verdict",
                "exit_code", "stdout", "stderr", "evidence", "duration_ms", "created_at"]
        return [{**dict(zip(keys, r)), "created_at": str(r[12])} for r in rows]
    except Exception:  # noqa: BLE001
        return []


def verify_finding(finding_id: int) -> dict:

    from codesentry.agents.runtime import prepare_agent
    from codesentry.config import get_settings
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT f.scan_id, f.path_id, f.rule_id, f.cwe, f.severity, f.file, f.line,"
            " f.message, s.repo_path FROM findings f JOIN scans s ON s.id=f.scan_id"
            " WHERE f.id=%s",
            (int(finding_id),),
        )
        row = cur.fetchone()
    if not row:
        raise ValueError("finding not found")
    scan_id, path_id, rule_id, cwe, severity, rel, line, message, repo = row
    root = Path(str(repo)).resolve()
    target = (root / str(rel)).resolve()
    if root not in target.parents and target != root:
        raise ValueError("finding file outside repo")
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        raise ValueError(f"源码不可读：{e}") from e
    start = max(1, int(line or 1) - 50)
    end = min(len(lines), int(line or 1) + 50)
    source = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))
    runtime = prepare_agent("audit", scan_id=int(scan_id), with_llm=True)
    if runtime is None or runtime.llm is None:
        raise RuntimeError("LLM 未配置，无法生成 Harness")
    finding = {"rule_id": rule_id, "cwe": cwe, "severity": severity,
               "file": rel, "line": line, "message": message}
    try:
        generated = generate_harness(runtime.llm, finding, source)
    except Exception as e:
        raise RuntimeError(f"Harness 生成失败：{str(e)[:200]}") from e
    settings = get_settings()
    result = run_harness(
        generated["code"], generated["language"], image=settings.harness_image,
        timeout_s=settings.harness_timeout_s, allow_network=settings.harness_allow_network,
        pull_policy=settings.harness_pull_policy,
    )
    rid = save_run(int(scan_id), int(finding_id), path_id, int(cwe or 0),
                   generated["language"], generated["code"], result,
                   {"summary": generated["summary"], "payloads": generated["payloads"],
                    "reason": result.get("reason")})
    if result.get("verdict") in ("verified", "rejected", "plausible"):
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute("UPDATE findings SET verdict=%s, execution_log=%s WHERE id=%s",
                            (result["verdict"], (result.get("stdout") or result.get("stderr") or "")[:4000],
                             int(finding_id)))
                conn.commit()
        except Exception:  # noqa: BLE001, S110
            pass
    return {"run_id": rid, "language": generated["language"],
            "summary": generated["summary"], "payloads": generated["payloads"],
            **result}
