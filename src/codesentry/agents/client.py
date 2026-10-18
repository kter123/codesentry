"""codesentry agents/skills 子命令实现（FR-11/FR-12 v1 CLI 面）。"""


import typer

from codesentry.agents.state import AGENT_NAMES


def agents_list() -> None:
    """agent 清单 + DB 配置状态（agent_configs；缺库时静默展示种子）。"""
    from rich.console import Console
    from rich.table import Table

    configs: dict[str, dict] = {}
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT name, enabled, model_role FROM agent_configs")
            for row in cur.fetchall():
                configs[row[0]] = {"enabled": row[1], "model_role": row[2]}
    except Exception:  # noqa: BLE001 - 无库展示种子清单
        pass

    table = Table(title="CodeSentry Agents")
    table.add_column("agent")
    table.add_column("enabled")
    table.add_column("model")
    for name in AGENT_NAMES:
        c = configs.get(name, {})
        table.add_row(name, str(c.get("enabled", "—")), c.get("model_role", "—"))
    Console().print(table)


def skills_cmd(
    action: str = typer.Argument("list", help="list|upload|enable"),
    name: str = typer.Argument("", help="skill 名 / upload 时的目录"),
    agent: str = typer.Argument("", help="enable 时的 agent"),
) -> None:
    if action == "list":
        _skills_list()
        return
    if action == "upload":
        if not name:
            typer.echo("用法：codesentry skills upload <skill-dir>", err=True)
            raise typer.Exit(2)
        _skills_upload(name)
        return
    if action == "enable":
        if not name or not agent:
            typer.echo("用法：codesentry skills enable <name> <agent>", err=True)
            raise typer.Exit(2)
        _skills_enable(name, agent)
        return
    typer.echo(f"未知子动作 {action}（list|upload|enable）", err=True)
    raise typer.Exit(2)


def _skills_list() -> None:
    from rich.console import Console
    from rich.table import Table

    from codesentry.db.pool import get_conn

    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT s.name, s.description, s.enabled, count(v.id) FROM skills s LEFT JOIN skill_versions v ON v.name = s.name GROUP BY s.name, s.description, s.enabled"
            )
            rows = cur.fetchall()
    except Exception:  # noqa: BLE001 - 无库时提示
        typer.echo("数据库未连接 — 请先 docker compose up -d && codesentry init-db", err=True)
        raise typer.Exit(1)
    table = Table(title="CodeSentry Skills")
    table.add_column("name")
    table.add_column("versions")
    table.add_column("enabled")
    table.add_column("description")
    for r in rows:
        table.add_row(r[0], str(r[3]), str(r[2]), r[1])
    Console().print(table)


def _skills_upload(path: str) -> None:
    from codesentry.agents.skills import load_skill_dir
    from codesentry.db.pool import get_conn

    try:
        skill = load_skill_dir(path)
    except Exception as e:  # noqa: BLE001 - 校验失败必须明确报错（§10）
        typer.echo(f"skill 校验失败：{e}", err=True)
        raise typer.Exit(1)
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO skills (name, description, enabled) VALUES (%s, %s, TRUE) ON CONFLICT (name) DO NOTHING",
                (skill.name, skill.description),
            )
            cur.execute("SELECT coalesce(max(version), 0) FROM skill_versions WHERE name = %s", (skill.name,))
            next_v = cur.fetchone()[0] + 1
            cur.execute(
                "INSERT INTO skill_versions (name, version, body, body_sha256) VALUES (%s,%s,%s,%s)",
                (skill.name, next_v, skill.body, _sha(skill.body)),
            )
            conn.commit()
    except Exception as e:  # noqa: BLE001
        typer.echo(f"skill 入库失败（先 init-db）：{e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"skill 上传成功：{skill.name} v{next_v}（references={len(skill.references)}）")


def _skills_enable(name: str, agent: str) -> None:
    from codesentry.db.pool import get_conn

    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO skill_assignments (skill_name, agent, enabled) VALUES (%s,%s,TRUE) ON CONFLICT (skill_name, agent) DO UPDATE SET enabled = TRUE",
                (name, agent),
            )
            conn.commit()
    except Exception as e:  # noqa: BLE001
        typer.echo(f"enable 失败：{e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"skill {name} 已指派给 {agent}")


def _sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
