import shutil
import subprocess

import typer
from rich.console import Console
from rich.table import Table

_MILESTONE_HINT = {
    "scan": "M1",
    "diff": "M3",
    "report": "M1",
    "kb": "M2",
    "agents": "M3",
    "skills": "M3",
}


def _not_implemented(cmd: str) -> int:
    typer.echo(f"[{_MILESTONE_HINT[cmd]}] {cmd} 未实现 — 见 agent.md §9 里程碑计划", err=True)
    return 1


def init_db(dry_run: bool = typer.Option(False, "--dry-run", help="只打印 DDL 不连库")) -> None:
    from codesentry.config import get_settings
    from codesentry.db.schema import render_ddl

    if dry_run:
        typer.echo(render_ddl())
        return
    try:
        import psycopg

        with psycopg.connect(get_settings().database_url) as conn:
            conn.execute(render_ddl())
        typer.echo("init-db 完成 — schema: codesentry, langgraph; extension: vector")
    except Exception as e:  # noqa: BLE001 - 连库入口需对所有连不上/执行失败给出明确指引
        typer.echo(f"init-db 失败：{e}", err=True)
        typer.echo("提示：先 docker compose up -d 启动数据库", err=True)
        raise typer.Exit(1)


def scan_cmd(
    oss: bool = typer.Option(False, "--oss", help="声明目标为开源代码（许可 Gate，M1 生效）"),
    skills: str = typer.Option(
        "", "--skills", help="本次扫描临时启用的 Skill 名单，逗号分隔（M3 生效）"
    ),
) -> None:
    raise typer.Exit(_not_implemented("scan"))


def diff_cmd(
    repo: str = typer.Argument("", help="仓库路径（M3 解析）"),
    base: str = typer.Argument("", help="基线 ref（M3 解析）"),
    head: str = typer.Argument("", help="目标 ref（M3 解析）"),
) -> None:
    raise typer.Exit(_not_implemented("diff"))


def report_cmd(scan_id: str = typer.Argument("", help="扫描 ID（M1 解析）")) -> None:
    raise typer.Exit(_not_implemented("report"))


def kb_cmd() -> None:
    raise typer.Exit(_not_implemented("kb"))


def agents_list() -> None:
    raise typer.Exit(_not_implemented("agents"))


def skills_cmd() -> None:
    raise typer.Exit(_not_implemented("skills"))


def _probe_java() -> str | None:
    which = shutil.which("java")
    if which is None:
        return None
    try:
        r = subprocess.run(
            [which, "-version"], capture_output=True, text=True, timeout=15, check=False
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    # java -version 输出走 stderr
    text = (r.stdout + r.stderr).strip()
    return text.splitlines()[0] if text else which


def engines_check() -> None:
    from codesentry.config import get_settings

    settings = get_settings()
    console = Console()
    table = Table(title="CodeSentry 引擎探测")
    table.add_column("组件", style="bold")
    table.add_column("路径")
    table.add_column("状态")

    engines = [
        ("codeql", settings.codeql_bin),
        ("joern", settings.joern_bin),
        ("semgrep", settings.semgrep_bin),
    ]
    missing = []
    for name, bin_name in engines:
        path = shutil.which(bin_name)
        if path:
            table.add_row(name, path, "[green]可用[/green]")
        else:
            table.add_row(name, bin_name, "[red]未找到[/red]")
            missing.append(name)

    java_version = _probe_java()
    if java_version:
        table.add_row("java", shutil.which("java") or "java", java_version)
    else:
        table.add_row("java", "java", "[yellow]未找到（Joern 需要 JDK 17+）[/yellow]")

    console.print(table)

    if len(missing) == 3:
        typer.echo("三个引擎全部缺失 — 请安装引擎或配置 CODESENTRY_*_BIN", err=True)
        raise typer.Exit(1)
