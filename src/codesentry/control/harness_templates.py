"""Harness 模板与 payload 组（clean-room）。"""

from __future__ import annotations

TEMPLATES = {
    78: {
        "name": "command-injection",
        "guidance": "mock os.system/subprocess/exec，记录被调用的命令；payload 包含 ; | && $(...) `...`。",
        "payloads": ["test", "; id", "| whoami", "&& echo VULN", "$(id)", "`id`"],
    },
    89: {
        "name": "sql-injection",
        "guidance": "mock cursor/ORM，检测字符串拼接、无参数化查询；payload 包含 ' OR '1'='1 与注释。",
        "payloads": ["1", "1'", "1' OR '1'='1", "1'; DROP TABLE x--", "1 UNION SELECT 1"],
    },
    79: {
        "name": "xss",
        "guidance": "调用渲染函数，检查 payload 是否原样进入 HTML；payload 包含 script/img/svg。",
        "payloads": ["<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "{{7*7}}"],
    },
    22: {
        "name": "path-traversal",
        "guidance": "mock 文件系统/路径解析，检查 ../ 是否逃逸 root；payload 包含 ../../etc/passwd 与编码变体。",
        "payloads": ["../etc/passwd", "....//....//etc/passwd", "..%2f..%2fetc%2fpasswd"],
    },
    94: {"name": "code-injection", "guidance": "mock eval/exec，检测用户输入进入执行。", "payloads": ["1+1", "__import__('os').getcwd()"]},
    95: {"name": "eval-injection", "guidance": "mock eval/Function，检测表达式执行。", "payloads": ["1+1", "process.version", "globals()"]},
    502: {"name": "deserialization", "guidance": "mock 反序列化入口，检测危险类型/对象构造。", "payloads": ["test", "{\"__reduce__\":\"x\"}"]},
    918: {"name": "ssrf", "guidance": "mock HTTP client，记录请求 URL；检测内网/回环地址。", "payloads": ["http://127.0.0.1/", "http://169.254.169.254/", "file:///etc/passwd"]},
    611: {"name": "xxe", "guidance": "mock XML parser，检测外部实体解析。", "payloads": ["<!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><x>&e;</x>"]},
    1333: {"name": "redos", "guidance": "执行目标正则并限制时间，检测灾难性回溯。", "payloads": ["a" * 1000 + "!", "(" * 50 + "a" + ")" * 50]},
}


def for_cwe(cwe: int) -> dict:
    return TEMPLATES.get(int(cwe or 0), {
        "name": "generic",
        "guidance": "根据 finding 构造最小 harness，mock 依赖，打印 HARNESS_VERIFIED/NOT_TRIGGERED。",
        "payloads": ["test"],
    })


def all_templates() -> list[dict]:
    return [{"cwe": cwe, **value} for cwe, value in sorted(TEMPLATES.items())]


def extract_function(scan_id: int, file: str, line: int) -> dict:
    from pathlib import Path

    from codesentry.db.pool import get_conn
    from codesentry.rag.graph_query import node, node_for_location

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT repo_path FROM scans WHERE id=%s", (int(scan_id),))
        row = cur.fetchone()
    if not row:
        raise ValueError("scan not found")
    root = Path(str(row[0])).resolve()
    project = str(root)
    key = node_for_location(project, file, int(line or 0))
    found = node(project, key) if key else None
    if not found:
        raise ValueError("function node not found")
    try:
        lines = (root / found["path"]).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        raise ValueError(f"source unreadable: {e}") from e
    start = max(1, int(found.get("start") or 1))
    end = min(len(lines), int(found.get("end") or start + 120))
    body = "\n".join(f"{i}: {lines[i-1]}" for i in range(start, end + 1))
    return {"key": key, "kind": found.get("kind"), "name": found.get("name"),
            "file": found.get("path"), "start": start, "end": end, "source": body[:16000]}
