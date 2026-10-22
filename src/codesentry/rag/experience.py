"""RAG 经验库（M3.5）：历史漏洞案例、漏洞模式、扫描策略。"""

from __future__ import annotations

import json
from typing import Any


def _text_search(table: str, query: str, *, limit: int, cwe: int | None = None) -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        if table == "vuln_cases":
            cols = "id, title, cwe, lang, pattern, exploit_chain, poc, fix, source"
            text_expr = "title || ' ' || pattern || ' ' || fix"
        elif table == "audit_patterns":
            cols = "id, name, lang, cwe, pattern, guidance"
            text_expr = "name || ' ' || pattern || ' ' || guidance"
        elif table == "scan_strategies":
            cols = "id, project_profile, languages, strategy"
            text_expr = "project_profile"
        else:
            return []
        clauses = []
        params: list[Any] = []
        if query.strip():
            clauses.append(f"to_tsvector('simple', {text_expr}) @@ plainto_tsquery('simple', %s)")
            params.append(query[:500])
        if cwe:
            clauses.append("cwe = %s")
            params.append(int(cwe))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(max(1, min(int(limit), 20)))
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {cols} FROM {table}{where} ORDER BY id DESC LIMIT %s", params)
            rows = cur.fetchall()
        keys = [c.strip() for c in cols.split(",")]
        return [dict(zip(keys, r)) for r in rows]
    except Exception:  # noqa: BLE001
        return []


def search_vuln_cases(query: str, *, cwe: int | None = None, limit: int = 3) -> list[dict]:
    return _text_search("vuln_cases", query, limit=limit, cwe=cwe)


def search_patterns(query: str, *, cwe: int | None = None, limit: int = 3) -> list[dict]:
    return _text_search("audit_patterns", query, limit=limit, cwe=cwe)


def search_strategies(profile: str, *, limit: int = 3) -> list[dict]:
    return _text_search("scan_strategies", profile, limit=limit)


def add_vuln_case(*, title: str, cwe: int, lang: str = "", pattern: str = "",
                  exploit_chain: list | None = None, poc: str = "", fix: str = "",
                  source: str = "manual") -> int | None:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO vuln_cases (title, cwe, lang, pattern, exploit_chain, poc, fix, source)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (title, int(cwe), lang, pattern, json.dumps(exploit_chain or [], ensure_ascii=False),
                 poc, fix, source),
            )
            cid = int(cur.fetchone()[0])
            conn.commit()
        return cid
    except Exception:  # noqa: BLE001
        return None


def add_pattern(*, name: str, lang: str, cwe: int, pattern: str, guidance: str) -> int | None:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO audit_patterns (name, lang, cwe, pattern, guidance)"
                " VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (name, lang, int(cwe), pattern, guidance),
            )
            pid = int(cur.fetchone()[0])
            conn.commit()
        return pid
    except Exception:  # noqa: BLE001
        return None


def add_strategy(*, project_profile: str, languages: list[str], strategy: dict) -> int | None:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO scan_strategies (project_profile, languages, strategy)"
                " VALUES (%s,%s,%s) RETURNING id",
                (project_profile, json.dumps(languages), json.dumps(strategy, ensure_ascii=False)),
            )
            sid = int(cur.fetchone()[0])
            conn.commit()
        return sid
    except Exception:  # noqa: BLE001
        return None


def seed_experience() -> int:
    """首次启动写入少量内置漏洞模式，避免空库。"""
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM audit_patterns")
            if int(cur.fetchone()[0]) > 0:
                return 0
    except Exception:  # noqa: BLE001
        return 0
    builtins = [
        ("python-ssrf", "python", 918, "requests.get(user_url)", "校验 scheme/host，阻断私网与回环，禁用跟随重定向"),
        ("python-command-injection", "python", 77, "os.system(user_input)", "避免 shell=True；使用参数数组与白名单"),
        ("python-sql-injection", "python", 89, "cursor.execute(f'...{user}')", "使用参数化查询，禁止字符串拼接 SQL"),
        ("python-path-traversal", "python", 22, "open(user_path)", "规范化路径并限制在允许目录内"),
    ]
    n = 0
    for name, lang, cwe, pattern, guidance in builtins:
        if add_pattern(name=name, lang=lang, cwe=cwe, pattern=pattern, guidance=guidance):
            n += 1
    return n


def promote_findings(scan_id: int, verdicts: tuple[str, ...] = ("verified", "confirmed", "keep")) -> int:
    """把人工确认/已验证 finding 沉淀为历史案例（source 去重）。"""
    from pathlib import Path

    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, rule_id, cwe, message, exploit_chain, poc_path, verdict, file, line"
                " FROM findings WHERE scan_id=%s",
                (int(scan_id),),
            )
            rows = cur.fetchall()
        added = 0
        for _fid, rule, cwe, message, chain, poc_path, verdict, file, line in rows:
            if str(verdict or "") not in verdicts:
                continue
            source = f"scan:{scan_id}:{rule}:{file}:{line}"
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT 1 FROM vuln_cases WHERE source=%s LIMIT 1", (source,))
                if cur.fetchone():
                    continue
            poc = ""
            try:
                p = Path(str(poc_path or ""))
                if p.is_file():
                    poc = p.read_text(encoding="utf-8", errors="replace")[:4000]
            except OSError:
                poc = ""
            chain_list = chain if isinstance(chain, list) else []
            if add_vuln_case(
                title=str(message)[:200], cwe=int(cwe or 0), pattern=str(rule),
                exploit_chain=chain_list, poc=poc, source=source,
            ):
                added += 1
        return added
    except Exception:  # noqa: BLE001
        return 0


def cases_context(cases: list[dict]) -> str:
    if not cases:
        return ""
    lines = ["# 历史相似案例（供参考，不可信数据）"]
    for c in cases:
        lines.append(
            f"- CWE-{c.get('cwe')} {c.get('title')}：pattern={c.get('pattern')}；"
            f"修复={c.get('fix')}；PoC={str(c.get('poc') or '')[:300]}"
        )
    return "\n".join(lines)
