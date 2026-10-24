"""可视化编排模板（M6.6）：校验、版本、激活。"""

from __future__ import annotations

import json

ALLOWED_NODES = {"recon", "graph_build", "scan", "audit", "triage", "deploy", "poc_gen", "human_review", "report"}
REQUIRED_NODES = {"recon", "scan", "report"}


def validate(config: dict) -> dict:
    errors: list[str] = []
    nodes = config.get("nodes")
    edges = config.get("edges")
    if not isinstance(nodes, list) or not nodes:
        errors.append("nodes 必须是非空数组")
        nodes = []
    if not isinstance(edges, list):
        errors.append("edges 必须是数组")
        edges = []
    ids: list[str] = []
    for node in nodes:
        nid = str(node.get("id") or "") if isinstance(node, dict) else ""
        if not nid:
            errors.append("节点缺少 id")
            continue
        if nid in ids:
            errors.append(f"重复节点：{nid}")
        if nid not in ALLOWED_NODES:
            errors.append(f"未知节点：{nid}")
        ids.append(nid)
    for required in REQUIRED_NODES:
        if required not in ids:
            errors.append(f"缺少必需节点：{required}")
    for edge in edges:
        if not isinstance(edge, dict):
            errors.append("边必须是对象")
            continue
        src, dst = str(edge.get("from") or ""), str(edge.get("to") or "")
        if src not in ids or dst not in ids:
            errors.append(f"边引用未知节点：{src}->{dst}")
        if src == dst:
            errors.append(f"不允许自环：{src}")
        if src == "triage" and dst == "audit":
            maximum = int(edge.get("max") or 0)
            if maximum < 1 or maximum > 3:
                errors.append("triage->audit 回边 max 必须在 1..3")
        else:
            # 只允许 triage -> audit 作为回边；其余边不得形成环
            if src in ids and dst in ids and ids.index(dst) < ids.index(src):
                errors.append(f"非法回边：{src}->{dst}")
    return {"ok": not errors, "errors": errors, "nodes": ids,
            "settings": config.get("settings") or {}}


def list_templates() -> list[dict]:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, version, config, active, created_at FROM graph_templates"
                " ORDER BY name, version DESC"
            )
            rows = cur.fetchall()
        return [
            {"id": r[0], "name": r[1], "version": r[2], "config": r[3],
             "active": bool(r[4]), "created_at": str(r[5])}
            for r in rows
        ]
    except Exception:  # noqa: BLE001
        return []


def create_template(name: str, config: dict, *, activate: bool = False, actor: str = "api") -> dict | None:
    result = validate(config)
    if not result["ok"]:
        raise ValueError("; ".join(result["errors"]))
    try:
        from codesentry.control.audit import audit_write
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT coalesce(max(version),0) FROM graph_templates WHERE name=%s", (name,)
            )
            version = int(cur.fetchone()[0]) + 1
            if activate:
                cur.execute("UPDATE graph_templates SET active=FALSE WHERE name=%s", (name,))
            cur.execute(
                "INSERT INTO graph_templates (name, version, config, active)"
                " VALUES (%s,%s,%s,%s) RETURNING id",
                (name, version, json.dumps(config, ensure_ascii=False), activate),
            )
            tid = int(cur.fetchone()[0])
            conn.commit()
        audit_write(actor, "create", "graph_template", f"{name}:{version}", None,
                    {"name": name, "version": version, "active": activate})
        return {"id": tid, "name": name, "version": version, "active": activate}
    except Exception:  # noqa: BLE001
        return None


def activate_template(template_id: int, actor: str = "api") -> bool:
    try:
        from codesentry.control.audit import audit_write
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT name FROM graph_templates WHERE id=%s", (template_id,))
            row = cur.fetchone()
            if not row:
                return False
            cur.execute("UPDATE graph_templates SET active=FALSE WHERE name=%s", (row[0],))
            cur.execute("UPDATE graph_templates SET active=TRUE WHERE id=%s", (template_id,))
            conn.commit()
        audit_write(actor, "activate", "graph_template", str(template_id), None, None)
        return True
    except Exception:  # noqa: BLE001
        return False


def get_active() -> dict | None:
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, version, config FROM graph_templates WHERE active"
                " ORDER BY id DESC LIMIT 1"
            )
            row = cur.fetchone()
        return {"id": row[0], "name": row[1], "version": row[2], "config": row[3]} if row else None
    except Exception:  # noqa: BLE001
        return None
