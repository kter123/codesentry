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


def _snapshot_agents() -> tuple[dict, dict, dict]:
    """兼容旧测试：返回 (prompt, skills, llm) 三段快照。"""
    from codesentry.control.snapshots import build_scan_snapshot

    snap = build_scan_snapshot()
    return (
        snap.get("prompt_versions", {}),
        snap.get("skills_snapshot", {}),
        snap.get("llm_snapshot", {}),
    )


def run_scan_graph(repo: str, OSS: bool, out_dir: str, scan_id: int | None = None) -> int:
    """LangGraph 全链路审计：落库 + 报告。返回进程退出码。"""
    from codesentry.agents.poc_gen import run_poc_gen
    from codesentry.agents.recon import build_profile
    from codesentry.agents.report import run_report
    from codesentry.agents.retrieval import run_retrieval
    from codesentry.agents.scan import run_scan_agent
    from codesentry.agents.triage import run_triage
    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.db.pool import get_conn
    from codesentry.orchestrator.human_review import human_review_node
    from codesentry.sandbox.deploy import run_deploy

    ensure_control_schema()
    from codesentry.config import get_settings

    if not get_settings().model_base_url:
        from codesentry.control.profiles import get_default

        if get_default() is None:
            typer.echo("LLM 未配置 — Triage/PoC 退化为引擎原始结论（未验证标签）", err=True)

    from codesentry.control.snapshots import build_scan_snapshot, snapshot_json

    reused = scan_id is not None and int(scan_id) > 0
    sid_in = int(scan_id) if scan_id is not None else 0
    snapshot: dict | None = None
    if reused:
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT prompt_snapshot, skill_snapshot, llm_snapshot FROM scans WHERE id=%s",
                    (sid_in,),
                )
                row = cur.fetchone()
            if row and any(row):
                snapshot = {
                    "prompt_versions": row[0] or {},
                    "skills_snapshot": row[1] or {},
                    "llm_snapshot": row[2] or {},
                }
        except Exception:  # noqa: BLE001
            snapshot = None
    if snapshot is None:
        snapshot = build_scan_snapshot()

    llm_snap = snapshot.get("llm_snapshot", {})
    profile_ids = [v.get("profile_id") for v in llm_snap.values() if v.get("profile_id")]
    default_pid = int(profile_ids[0]) if profile_ids else None
    graph_snap = json.dumps({"template": "default", "version": 1}, ensure_ascii=False)

    # scans 落库 / 复用 Web 已插入的 scan_id
    try:
        with get_conn() as conn, conn.cursor() as cur:
            from datetime import datetime

            declared_at = datetime.now(UTC)
            snaps = snapshot_json(snapshot)
            if reused:
                cur.execute(
                    "UPDATE scans SET status='running', prompt_snapshot=%s, skill_snapshot=%s,"
                    " llm_snapshot=%s, llm_profile_id=%s, graph_snapshot=%s, report_dir=%s"
                    " WHERE id=%s RETURNING id",
                    (*snaps, default_pid, graph_snap, out_dir, sid_in),
                )
                row = cur.fetchone()
                scan_id = int(row[0]) if row else sid_in
            else:
                cur.execute(
                    "INSERT INTO scans (repo_path, license_oss, license_declared_at, mode, status,"
                    " prompt_snapshot, skill_snapshot, llm_snapshot, llm_profile_id, graph_snapshot, report_dir)"
                    " VALUES (%s,%s,%s,'full','running',%s,%s,%s,%s,%s,%s) RETURNING id",
                    (repo, OSS, declared_at, *snaps, default_pid, graph_snap, out_dir),
                )
                scan_id = int(cur.fetchone()[0])
            conn.commit()
    except Exception as e:  # noqa: BLE001 - 无库时warning继续（文件报告仍产出）
        scan_id = int(scan_id or 0)
        typer.echo(f"scans 落库失败（无库？）：{e}", err=True)

    budget = BudgetGuard(scan_id=scan_id)
    holder = {"scan_id": scan_id, "budget": budget, "snapshot": snapshot}

    try:
        st = new_state(repo, OSS, scan_id=scan_id)
        st["profile"] = build_profile(repo)
    except Exception as e:  # noqa: BLE001
        typer.echo(f"scan 初始化失败：{e}", err=True)
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE scans SET status='failed', error_reason=%s WHERE id=%s",
                    (str(e)[:500], scan_id),
                )
                conn.commit()
        except Exception:  # noqa: BLE001, S110
            pass
        return 1

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
        deploy_agent=run_deploy,
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
                    cur.execute(
                        "UPDATE scans SET status='failed', error_reason=%s WHERE id=%s",
                        (str(e)[:500], scan_id),
                    )
                    conn.commit()
            except Exception:  # noqa: BLE001, S110
                pass
        if cp_ctx is not None:
            cp_ctx.__exit__(type(e), e, e.__traceback__)
        return 1

    # findings 落库；无论成功失败都收敛 scans.status
    status = "done"
    err_text = ""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            for tf in final.get("triaged_findings") or []:
                poc = tf.get("poc") or {}
                cur.execute(
                    """
                    INSERT INTO findings (scan_id, rule_id, cwe, severity, confidence, file, line, message, engine,
                                          taint_metadata, exploit_chain, poc_path, verdict, execution_log,
                                          verification_method, verification_nonce, confidence_parts)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
                        poc.get("verification_method") or "",
                        poc.get("verification_nonce") or "",
                        json.dumps(tf.get("confidence_parts") or {}),
                    ),
                )
            conn.commit()
    except Exception as e:  # noqa: BLE001
        status = "failed"
        err_text = str(e)[:500]
        typer.echo(f"findings 落库失败：{e}", err=True)
    finally:
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE scans SET status=%s, error_reason=%s, deploy_status=%s,"
                    " deploy_log=%s, target_url=%s WHERE id=%s",
                    (
                        status, err_text,
                        str(final.get("deploy_status") or ""),
                        str(final.get("deploy_log") or "")[:4000],
                        str(final.get("target_url") or ""),
                        scan_id,
                    ),
                )
                conn.commit()
        except Exception:  # noqa: BLE001, S110
            pass

    typer.echo(f"scan 完成：scan_id={scan_id}，report 在 {out_dir}")
    return 0 if status == "done" else 1
