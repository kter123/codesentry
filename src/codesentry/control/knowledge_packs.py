"""知识包：框架/漏洞/策略文本，版本化与检索加权。"""

from __future__ import annotations

BUILTINS = [
    {"name": "framework/flask", "kind": "framework", "lang": "python", "framework": "flask",
     "cwe": 0, "content": "Flask: request.args/form/json 是典型 source；@app.route 是入口；render_template_string 与 eval 属高危 sink。"},
    {"name": "framework/fastapi", "kind": "framework", "lang": "python", "framework": "fastapi",
     "cwe": 0, "content": "FastAPI: Query/Body/Path 参数是 source；Depends 鉴权需沿依赖链检查；子进程/文件/HTTP 客户端是 sink。"},
    {"name": "framework/django", "kind": "framework", "lang": "python", "framework": "django",
     "cwe": 0, "content": "Django: request.GET/POST 是 source；ORM raw/extra 与 mark_safe 需重点审计；CSRF/认证中间件影响可达性。"},
    {"name": "framework/express", "kind": "framework", "lang": "javascript", "framework": "express",
     "cwe": 0, "content": "Express: req.query/body/params 是 source；child_process、fs、eval、模板拼接是 sink；中间件鉴权要与路由匹配。"},
    {"name": "framework/spring", "kind": "framework", "lang": "java", "framework": "spring",
     "cwe": 0, "content": "Spring: @RequestParam/@PathVariable/@RequestBody 是 source；Runtime.exec、JDBC 拼接、文件路径、反序列化是 sink；检查 @PreAuthorize/Shiro。"},
    {"name": "vuln/sql-injection", "kind": "vuln", "lang": "", "framework": "", "cwe": 89,
     "content": "SQL 注入：source 进入字符串拼接/ORM raw；参数化查询是净化；检查 MyBatis ${}、JPA native、Django raw。"},
    {"name": "vuln/command-injection", "kind": "vuln", "lang": "", "framework": "", "cwe": 78,
     "content": "命令注入：source 进入 Runtime.exec/os.system/subprocess/child_process；数组 argv 且无 shell 是净化；检查命令拼接与 shell=True。"},
    {"name": "vuln/path-traversal", "kind": "vuln", "lang": "", "framework": "", "cwe": 22,
     "content": "路径遍历：文件名/路径 source 进入 File/Paths/open/fs；规范化并校验 root 前缀是净化；检查 ../ 与编码变体。"},
    {"name": "vuln/ssrf", "kind": "vuln", "lang": "", "framework": "", "cwe": 918,
     "content": "SSRF：URL source 进入 HTTP 客户端；白名单 host/协议、禁私网是净化；检查重定向与 DNS rebinding。"},
    {"name": "vuln/deserialization", "kind": "vuln", "lang": "", "framework": "", "cwe": 502,
     "content": "反序列化：不可信输入进入 ObjectInputStream/readObject/pickle/Jackson default typing；白名单类型是净化。"},
]


def _row(r: tuple) -> dict:
    keys = ["id", "name", "kind", "lang", "framework", "cwe", "version", "content",
            "source", "enabled", "created_at", "updated_at"]
    out = dict(zip(keys, r))
    out["created_at"] = str(out["created_at"])
    out["updated_at"] = str(out["updated_at"])
    return out


def list_packs(kind: str = "", enabled: bool | None = None) -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        sql = ("SELECT id, name, kind, lang, framework, cwe, version, content, source,"
               " enabled, created_at, updated_at FROM knowledge_packs WHERE 1=1")
        params: list = []
        if kind:
            sql += " AND kind=%s"
            params.append(kind)
        if enabled is not None:
            sql += " AND enabled=%s"
            params.append(bool(enabled))
        sql += " ORDER BY id"
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [_row(r) for r in rows]
    except Exception:  # noqa: BLE001
        return []


def create_pack(name: str, content: str, *, kind: str = "vuln", lang: str = "",
                framework: str = "", cwe: int = 0, source: str = "user") -> dict:
    if not name.strip() or not content.strip():
        raise ValueError("name/content 必填")
    if len(content) > 200_000:
        raise ValueError("content too large")
    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.db.pool import get_conn

    ensure_control_schema()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT coalesce(max(version),0)+1 FROM knowledge_packs WHERE name=%s", (name,))
        version = int(cur.fetchone()[0])
        cur.execute(
            "INSERT INTO knowledge_packs (name, kind, lang, framework, cwe, version, content, source)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (name, kind, lang, framework, int(cwe or 0), version, content, source),
        )
        pid = int(cur.fetchone()[0])
        conn.commit()
    return next(p for p in list_packs() if int(p["id"]) == pid)


def update_pack(pack_id: int, patch: dict) -> dict | None:
    current = next((p for p in list_packs() if int(p["id"]) == int(pack_id)), None)
    if not current:
        return None
    from codesentry.db.pool import get_conn

    fields = {**current, **{k: patch[k] for k in (
        "name", "kind", "lang", "framework", "cwe", "content", "enabled"
    ) if k in patch}}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE knowledge_packs SET name=%s, kind=%s, lang=%s, framework=%s, cwe=%s,"
            " content=%s, enabled=%s, version=version+1, updated_at=now() WHERE id=%s",
            (fields["name"], fields["kind"], fields["lang"], fields["framework"],
             int(fields["cwe"] or 0), fields["content"], bool(fields["enabled"]),
             int(pack_id)),
        )
        conn.commit()
    return next(p for p in list_packs() if int(p["id"]) == int(pack_id))


def delete_pack(pack_id: int) -> bool:
    from codesentry.db.pool import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM knowledge_packs WHERE id=%s", (int(pack_id),))
        ok = cur.rowcount > 0
        conn.commit()
    return ok


def seed_builtins() -> int:
    existing = {p["name"] for p in list_packs()}
    n = 0
    for item in BUILTINS:
        if item["name"] in existing:
            continue
        try:
            create_pack(str(item["name"]), str(item["content"]),
                        kind=str(item["kind"]), lang=str(item["lang"]),
                        framework=str(item["framework"]),
                        cwe=int(str(item["cwe"] or 0)), source="builtin")
            n += 1
        except Exception:  # noqa: BLE001, S112
            continue
    return n


def search(query: str, *, lang: str = "", framework: str = "",
           cwe: int = 0, limit: int = 5) -> list[dict]:
    words = [w for w in str(query).lower().split() if w]
    scored: list[tuple[float, dict]] = []
    for pack in list_packs(enabled=True):
        text = f"{pack['name']} {pack['content']}".lower()
        score = sum(1 for w in words if w in text)
        if lang and pack.get("lang") == lang:
            score += 2
        if framework and pack.get("framework") == framework:
            score += 3
        if cwe and int(pack.get("cwe") or 0) == int(cwe):
            score += 4
        if score:
            scored.append((score, {**pack, "score": score,
                                   "source_ref": f"pack:{pack['name']}@v{pack['version']}"}))
    scored.sort(key=lambda x: (-x[0], x[1]["name"]))
    return [p for _s, p in scored[: max(1, min(int(limit), 20))]]
