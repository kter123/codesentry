"""LangGraph 版完整审计流水线（agent.md §7/§9 M3）：CLI scan 走 graph 全链路。

替代 scan_orchestrator.run_scan 的函数级直通版：保留引擎层，编排走 graph。
落库：scans + findings + node_runs + budget_ledger（FR-7/FR-9/NFR-2）。
"""

import json
import os
from datetime import UTC

import typer

from codesentry.agents.state import new_state
from codesentry.orchestrator.budget import BudgetGuard
from codesentry.orchestrator.checkpointer import checkpointer
from codesentry.orchestrator.graph import build_graph


def run_scan_graph(repo: str, OSS: bool, out_dir: str) -> int:
    """LangGraph 全链路审计：落库 + 报告。返回进程退出码。"""
    from codesentry.agents.llm import LLMClient
    from codesentry.agents.poc_gen import run_poc_gen
    from codesentry.agents.recon import build_profile
    from codesentry.agents.report import run_report
    from codesentry.agents.retrieval import run_retrieval
    from codesentry.agents.scan import run_scan_agent
    from codesentry.agents.triage import run_triage
    from codesentry.db.pool import get_conn
    from codesentry.orchestrator.human_review import human_review_node

    llm = None
    try:
        llm = LLMClient.from_config()
    except Exception:  # noqa: BLE001 - LLM 未配时退化 triage/poc（无验证模式）
        typer.echo("LLM 未配置 — Triage/PoC 退化为引擎原始结论（未验证标签）", err=True)

    # scans 落库
    scan_id = 0
    try:
        with get_conn() as conn, conn.cursor() as cur:
            from datetime import datetime

            declared_at = datetime.now(UTC)
            cur.execute(
                "INSERT INTO scans (repo_path, license_oss, license_declared_at, mode, status) VALUES (%s,%s,%s,'full','running') RETURNING id",
                (repo, OSS, declared_at),
            )
            scan_id = cur.fetchone()[0]
            conn.commit()
    except Exception as e:  # noqa: BLE001 - 无库时warning继续（文件报告仍产出）
        typer.echo(f"scans 落库失败（无库？）：{e}", err=True)

    budget = BudgetGuard(scan_id=scan_id)
    holder = {"scan_id": scan_id, "budget": budget}

    st = new_state(repo, OSS, scan_id=scan_id)
    st["profile"] = build_profile(repo)

    cp = None
    cp_ctx = None
    try:
        cp_ctx = checkpointer()
        cp = cp_ctx.__enter__()
    except Exception:  # noqa: BLE001 - 无库时无 checkpointer（文件输出仍可用）
        cp = None

    g = build_graph(
        scan_agent=run_scan_agent,
        retrieval_agent=run_retrieval,
        triage_agent=run_triage,
        poc_agent=run_poc_gen,
        report_agent_fn=lambda s, out=out_dir: run_report(s, out),
        checkpointer=cp,
        scan_id_holder=holder,
        human_review_node=human_review_node if os.environ.get("CODESENTRY_HUMAN_REVIEW", "false").lower() == "true" else None,
    )

    try:
        cfg = {"configurable": {"thread_id": f"scan-{scan_id}"}, "recursion_limit": 30}
        final = g.invoke(st, config=cfg)
        if cp_ctx is not None:
            cp_ctx.__exit__(None, None, None)
    except Exception as e:  # noqa: BLE001 - 主流程异常落因
        typer.echo(f"scan 失败：{e}", err=True)
        if scan_id:
            try:
                with get_conn() as conn, conn.cursor() as cur:
                    cur.execute("UPDATE scans SET status='failed' WHERE id=%s", (scan_id,))
                    conn.commit()
            except Exception:  # noqa: BLE001, S110
                pass
        if cp_ctx is not None:
            cp_ctx.__exit__(type(e), e, e.__traceback__)
        return 1

    # findings 落库
    try:
        with get_conn() as conn, conn.cursor() as cur:
            for tf in final.get("triaged_findings") or []:
                tri = tf.get("triage") or {}
                poc = tf.get("poc") or {}
                cur.execute(
                    """
                    INSERT INTO findings (scan_id, rule_id, cwe, severity, confidence, file, line, message, engine,
                                          taint_metadata, exploit_chain, poc_path, verdict, execution_log)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        scan_id, tf.get("rule_id"), tf.get("cwe"), tf.get("severity"),
                        tf.get("confidence"), tf.get("file"), tf.get("line"),
                        tf.get("message"), tf.get("engine"),
                        json.dumps(tf.get("taint_metadata") or {}),
                        json.dumps(poc.get("exploit_chain") or []),
                        poc.get("poc_file") or "",
                        poc.get("verdict") or "",
                        (poc.get("execution_log") or "")[:4000],
                    ),
                )
            cur.execute("UPDATE scans SET status='done' WHERE id=%s", (scan_id,))
            conn.commit()
    except Exception as e:  # noqa: BLE001
        typer.echo(f"findings 落库失败：{e}", err=True)

    typer.echo(f"scan 完成：scan_id={scan_id}，report 在 {out_dir}")
    return 0
