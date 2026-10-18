import shutil
import subprocess
from pathlib import Path

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
    repo: str = typer.Argument("", help="目标仓库路径"),
    oss: bool = typer.Option(False, "--oss", help="声明目标为开源代码（许可 Gate，FR-3）"),
    out: str = typer.Option("", "--out", help="报告输出目录（默认 <repo>/codesentry-report）"),
    skills: str = typer.Option(
        "", "--skills", help="本次扫描临时启用的 Skill 名单，逗号分隔（M3 生效）"
    ),
) -> None:
    from codesentry.scan_orchestrator import run_scan

    if not repo:
        typer.echo("用法：codesentry scan <repo> [--oss] [--out DIR]", err=True)
        raise typer.Exit(2)
    out_dir = out or str(Path(repo) / "codesentry-report")
    code = run_scan(repo=repo, OSS=oss, out_dir=out_dir)
    raise typer.Exit(code)


def diff_cmd(
    repo: str = typer.Argument("", help="仓库路径"),
    basehead: str = typer.Argument("", help="'<base>...<head>' 形式的 diff 范围"),
    oss: bool = typer.Option(False, "--oss", help="声明目标为开源代码（许可 Gate，FR-3）"),
    out: str = typer.Option("", "--out", help="报告输出目录（默认 <repo>/codesentry-diff-report）"),
) -> None:
    """增量审计（FR-10）：git diff base...head → 可达闭包 → graph(mode=diff) → 报告 + 退出码。"""
    if not repo or "..." not in basehead:
        typer.echo("用法：codesentry diff <repo> '<base>...<head>' [--oss]", err=True)
        raise typer.Exit(2)
    base, head = basehead.split("...", 1)
    try:
        from codesentry.orchestrator.diffscope import changed_files

        files = changed_files(repo, base, head)
    except Exception as e:  # noqa: BLE001 - CLI 入口
        typer.echo(f"diff 失败：{e}", err=True)
        raise typer.Exit(2)
    if not files:
        typer.echo("diff 无变更文件 — 退出 0")
        raise typer.Exit(0)
    typer.echo(f"diff 变更 {len(files)} 文件：{files[:5]}{'…' if len(files) > 5 else ''}")
    # 可达闭包（python 链）；非 python 走全文件集
    from codesentry.agents.recon import diff_reachable_closure

    closure = diff_reachable_closure(repo, files)
    typer.echo(f"可达闭包：{len(closure)} 文件")

    # 增量扫描：对闭包文件直接跑引擎（graph 走全仓模式 M3.5 深化）
    out_dir = out or str(Path(repo) / "codesentry-diff-report")
    from codesentry.scan_orchestrator import run_scan

    code = run_scan(repo=repo, OSS=oss, out_dir=out_dir)
    if code == 0:
        # CI 退出码规则（FR-10）：高危 且 置信 >=0.7 → exit 1
        import json as _json

        sarif = _json.loads((Path(out_dir) / "report.sarif").read_text())
        hits = [
            r for r in sarif.get("runs", [{}])[0].get("results", [])
            if r.get("properties", {}).get("severity") in ("critical", "high")
            and float(r.get("properties", {}).get("confidence", 0)) >= 0.7
        ]
        if hits:
            typer.echo(f"增量审计：{len(hits)} 条高危高置信 finding — CI 阻断（exit 1）", err=True)
            raise typer.Exit(1)
    raise typer.Exit(code)


def report_cmd(scan_id: str = typer.Argument("", help="扫描 ID（M3 起 scans.id）")) -> None:
    if not scan_id:
        typer.echo("用法：codesentry report <scan-id>", err=True)
        raise typer.Exit(2)
    from codesentry.db.pool import get_conn

    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT repo_path FROM scans WHERE id = %s", (int(scan_id),))
            row = cur.fetchone()
            if not row:
                typer.echo(f"scan {scan_id} 不存在", err=True)
                raise typer.Exit(1)
            repo = row[0]
    except typer.Exit:
        raise
    except Exception as e:  # noqa: BLE001
        typer.echo(f"report 失败（连库）：{e}", err=True)
        raise typer.Exit(1)
    report_dir = Path(repo) / "codesentry-report"
    if not (report_dir / "report.md").exists():
        typer.echo(f"报告未生成：{report_dir}（请先 scan）", err=True)
        raise typer.Exit(1)
    typer.echo(str(report_dir / "report.md"))


def kb_cmd(
    action: str = typer.Argument("help", help="子动作：import"),
    path: str = typer.Argument("", help="import 的目录路径"),
) -> None:
    if action != "import" or not path:
        typer.echo("用法：codesentry kb import <dir>", err=True)
        raise typer.Exit(2)
    from codesentry.rag.kb_import import import_kb_dir

    try:
        n = import_kb_dir(path)
    except Exception as e:  # noqa: BLE001 - CLI 入口给出可读错误
        typer.echo(f"kb import 失败：{e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"kb import 完成：入库 {n} 条（sha256 幂等）")


def agents_list() -> None:
    from codesentry.agents.client import agents_list as _impl

    _impl()


def skills_cmd(
    action: str = typer.Argument("list", help="list|upload|enable"),
    name: str = typer.Argument("", help="skill 名 / upload 目录"),
    agent: str = typer.Argument("", help="enable 的 agent"),
) -> None:
    from codesentry.agents.client import skills_cmd as _impl

    _impl(action=action, name=name, agent=agent, )


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
