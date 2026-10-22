"""Prompt 版本与激活（M6.1 FR-23 基础闭环）。"""

from __future__ import annotations

import difflib
import hashlib
import re

_DANGEROUS = [
    (re.compile(r"\brm\s+-rf\b"), "包含 rm -rf"),
    (re.compile(r"\bsudo\b"), "包含 sudo"),
    (re.compile(r"\bcurl\b.*\|\s*(ba)?sh\b"), "包含管道执行"),
    (re.compile(r"/dev/tcp/"), "包含反弹 shell 模板"),
]


def _sha(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def list_prompts() -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT ON (agent) agent, version, active, body_sha256, body"
                " FROM prompt_versions ORDER BY agent, version DESC"
            )
            rows = cur.fetchall()
            cur.execute("SELECT agent, version FROM prompt_versions WHERE active")
            active = {r[0]: r[1] for r in cur.fetchall()}
        return [
            {
                "name": r[0],
                "latest_version": int(r[1]),
                "active_version": active.get(r[0]),
                "body_sha256": r[3] or "",
                "preview": (r[4] or "")[:120],
            }
            for r in rows
        ]
    except Exception:  # noqa: BLE001
        return []


def get_versions(agent: str) -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT version, body, active, body_sha256, created_at FROM prompt_versions"
                " WHERE agent=%s ORDER BY version DESC",
                (agent,),
            )
            rows = cur.fetchall()
        return [
            {"version": int(r[0]), "body": r[1], "active": bool(r[2]),
             "body_sha256": r[3] or "", "created": str(r[4]), "created_at": str(r[4])}
            for r in rows
        ]
    except Exception:  # noqa: BLE001
        return []


def get_version(agent: str, version: int) -> dict | None:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT version, body, body_sha256 FROM prompt_versions"
                " WHERE agent=%s AND version=%s",
                (agent, int(version)),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {"version": int(row[0]), "body": row[1], "body_sha256": row[2] or _sha(row[1])}
    except Exception:  # noqa: BLE001
        return None


def pick_version(agent: str, scan_id: int | None = None) -> tuple[int | None, str]:
    """A/B 分流：按 scan_id + agent 稳定分桶；未启用时返回 active 版本。"""
    try:
        from codesentry.control.agent_config import get_agent_config

        ab = (get_agent_config(agent).get("ab_json") or {})
        if ab.get("enabled") and ab.get("a") and ab.get("b"):
            ratio = float(ab.get("ratio", 0.5))
            bucket = ((int(scan_id or 0) * 31 + sum(ord(c) for c in agent)) % 100) / 100.0
            if bucket < ratio:
                return int(ab["b"]), "b"
            return int(ab["a"]), "a"
    except Exception:  # noqa: BLE001, S110
        pass
    active = get_active(agent)
    return (int(active["version"]) if active else None), "active"


def get_active(agent: str) -> dict | None:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT version, body, body_sha256 FROM prompt_versions"
                " WHERE agent=%s AND active ORDER BY version DESC LIMIT 1",
                (agent,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {"version": int(row[0]), "body": row[1], "body_sha256": row[2] or _sha(row[1])}
    except Exception:  # noqa: BLE001
        return None


def create_version(agent: str, body: str, *, activate: bool = True, actor: str = "system") -> int | None:
    try:
        from codesentry.control.audit import audit_write
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        sha = _sha(body)
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT coalesce(max(version),0) FROM prompt_versions WHERE agent=%s", (agent,))
            nv = int(cur.fetchone()[0]) + 1
            if activate:
                cur.execute("UPDATE prompt_versions SET active=FALSE WHERE agent=%s AND active", (agent,))
            cur.execute(
                "INSERT INTO prompt_versions (agent, version, body, body_sha256, active)"
                " VALUES (%s,%s,%s,%s,%s)",
                (agent, nv, body, sha, activate),
            )
            conn.commit()
        audit_write(actor, "create", "prompt", f"{agent}:{nv}", None,
                    {"version": nv, "sha256": sha, "active": activate})
        return nv
    except Exception:  # noqa: BLE001
        return None


def activate(agent: str, version: int, actor: str = "system") -> bool:
    try:
        from codesentry.control.audit import audit_write
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT body FROM prompt_versions WHERE agent=%s AND version=%s", (agent, version)
            )
            row = cur.fetchone()
            if not row:
                return False
            cur.execute("UPDATE prompt_versions SET active=FALSE WHERE agent=%s AND active", (agent,))
            cur.execute(
                "UPDATE prompt_versions SET active=TRUE, body_sha256=%s WHERE agent=%s AND version=%s",
                (_sha(row[0]), agent, version),
            )
            conn.commit()
        audit_write(actor, "activate", "prompt", f"{agent}:{version}", None, {"active_version": version})
        return True
    except Exception:  # noqa: BLE001
        return False


def rollback(agent: str, version: int, actor: str = "system") -> int | None:
    versions = {v["version"]: v for v in get_versions(agent)}
    if version not in versions:
        return None
    return create_version(agent, versions[version]["body"], activate=True, actor=actor)


def diff(agent: str, a: int, b: int) -> str:
    versions = {v["version"]: v["body"] for v in get_versions(agent)}
    if a not in versions or b not in versions:
        raise ValueError("version not found")
    return "\n".join(
        difflib.unified_diff(
            versions[a].splitlines(),
            versions[b].splitlines(),
            fromfile=f"{agent}:v{a}",
            tofile=f"{agent}:v{b}",
            lineterm="",
        )
    )


def lint(body: str, max_chars: int = 200_000) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    if not body.strip():
        errors.append("Prompt 为空")
    if len(body) > max_chars:
        errors.append(f"Prompt 超过 {max_chars} 字符")
    for pat, msg in _DANGEROUS:
        if pat.search(body):
            errors.append(f"危险指令：{msg}")
    if "JSON" not in body and "json" not in body:
        warnings.append("未声明输出 JSON 结构")
    if "untrusted" not in body.lower() and "不可信" not in body:
        warnings.append("未声明不可信内容分隔/指令层级")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


EVAL_CASES: list[dict] = [
    {
        "finding": {"rule_id": "eval.ssrf", "cwe": 918, "line": 1, "severity": "HIGH",
                    "message": "user controlled URL passed to requests.get", "file": "app.py"},
        "evidence": {"code": [{"path": "app.py", "snippet": "requests.get(request.args['url'])"}],
                     "vuln_cases": [], "patterns": []},
        "label": "keep",
    },
    {
        "finding": {"rule_id": "eval.sqli", "cwe": 89, "line": 2, "severity": "HIGH",
                    "message": "sql string concatenation with user input", "file": "db.py"},
        "evidence": {"code": [{"path": "db.py", "snippet": "cursor.execute('...'+name)"}],
                     "vuln_cases": [], "patterns": []},
        "label": "keep",
    },
    {
        "finding": {"rule_id": "eval.safe", "cwe": 89, "line": 3, "severity": "LOW",
                    "message": "parameterized query", "file": "safe.py"},
        "evidence": {"code": [{"path": "safe.py", "snippet": "cursor.execute('... WHERE id=%s', (id,))"}],
                     "vuln_cases": [], "patterns": []},
        "label": "reject",
    },
]


def run_prompt_eval(agent: str, version: int | None = None, dataset: str = "selfbuilt",
                    limit: int = 10) -> dict:
    """对内置/指定数据集跑真实 Triage，记录 recall/precision/FP/ECE。"""
    from codesentry.agents.llm import LLMClient, LLMError
    from codesentry.agents.triage import triage_one

    body = None
    if version is not None:
        pv = get_version(agent, version)
        if not pv:
            raise ValueError(f"prompt version not found: {agent} v{version}")
        body = pv["body"]
    try:
        llm = LLMClient.for_agent(agent)
    except Exception as e:
        raise LLMError(f"LLM 不可用：{e}") from e
    cases = EVAL_CASES[: max(1, min(int(limit), len(EVAL_CASES)))]
    tp = fp = tn = fn = 0
    conf_pairs: list[dict] = []
    for case in cases:
        out = triage_one(llm, case["finding"], case["evidence"], system=body)
        predicted = str(out.get("verdict") or "keep") != "reject"
        actual = case["label"] == "keep"
        if predicted and actual:
            tp += 1
        elif predicted and not actual:
            fp += 1
        elif not predicted and actual:
            fn += 1
        else:
            tn += 1
        conf_pairs.append({"raw": float(out.get("confidence") or 0.5), "label": 1.0 if actual else 0.0})
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    fp_rate = fp / (fp + tn) if (fp + tn) else 0.0
    try:
        from codesentry.control.calibration import ece as _ece

        ece = _ece(conf_pairs, 1.0, 0.0)
    except Exception:  # noqa: BLE001
        ece = 0.0
    metrics = {
        "recall": recall, "precision": precision, "fp_rate": fp_rate,
        "false_negatives": fn, "ece": ece, "n": len(cases),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
    }
    record_eval(agent, version, dataset, metrics)
    return {"agent": agent, "version": version, "dataset": dataset, "metrics": metrics}


def record_eval(agent: str, version: int | None, dataset: str, metrics: dict) -> bool:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO prompt_evals (agent, version, dataset, recall, precision,"
                " fp_rate, false_negatives, ece, n) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    agent, version, dataset, float(metrics.get("recall", 0)),
                    float(metrics.get("precision", 0)), float(metrics.get("fp_rate", 0)),
                    int(metrics.get("false_negatives", 0)), float(metrics.get("ece", 0)),
                    int(metrics.get("n", 0)),
                ),
            )
            conn.commit()
        return True
    except Exception:  # noqa: BLE001
        return False


def list_evals(agent: str | None = None, limit: int = 100) -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            if agent:
                cur.execute(
                    "SELECT id, agent, version, dataset, recall, precision, fp_rate,"
                    " false_negatives, ece, n, created_at FROM prompt_evals"
                    " WHERE agent=%s ORDER BY id DESC LIMIT %s",
                    (agent, max(1, min(int(limit), 500))),
                )
            else:
                cur.execute(
                    "SELECT id, agent, version, dataset, recall, precision, fp_rate,"
                    " false_negatives, ece, n, created_at FROM prompt_evals"
                    " ORDER BY id DESC LIMIT %s",
                    (max(1, min(int(limit), 500)),),
                )
            rows = cur.fetchall()
        keys = ["id", "agent", "version", "dataset", "recall", "precision", "fp_rate",
                "false_negatives", "ece", "n", "created_at"]
        return [dict(zip(keys, (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], str(r[10]))))
                for r in rows]
    except Exception:  # noqa: BLE001
        return []
