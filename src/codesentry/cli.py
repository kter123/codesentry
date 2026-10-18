import typer

from codesentry import bench, bench_top, cli_commands

app = typer.Typer(no_args_is_help=True, help="CodeSentry — LLM multi-agent code audit platform")

app.command(name="init-db")(cli_commands.init_db)
app.command(name="scan")(cli_commands.scan_cmd)
app.command(name="diff")(cli_commands.diff_cmd)
app.command(name="report")(cli_commands.report_cmd)
app.command(name="kb")(cli_commands.kb_cmd)
app.command(name="engines")(cli_commands.engines_check)
app.command(name="agents")(cli_commands.agents_list)
app.command(name="skills")(cli_commands.skills_cmd)
app.command(name="bench")(bench.bench_cmd)
app.command(name="bench-top")(bench_top.fullchain_cmd)
