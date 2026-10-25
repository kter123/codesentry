"""清理历史分析数据（扫描/证据/图谱/评测），保留控制面配置。

用法：
    PYTHONPATH=src uv run python scripts/purge_analysis_data.py --yes

保留：llm_profiles、app_settings、prompt_versions、skills、agent_configs、
users、api_tokens、webhooks、graph_templates、rule_sets、audit_patterns。
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ANALYSIS_TABLES = [
    "review_comments",
    "agent_artifacts",
    "findings",
    "node_runs",
    "budget_ledger",
    "llm_usage",
    "code_graph_edges",
    "code_graph_nodes",
    "graph_edges",
    "graph_nodes",
    "graph_endpoints",
    "graph_files",
    "graph_builds",
    "audit_paths",
    "audit_rounds",
    "agent_events",
    "agent_nodes",
    "scan_controls",
    "verification_runs",
    "tool_runs",
    "code_chunks",
    "kb_chunks",
    "knowledge_packs",
    "vuln_cases",
    "scan_strategies",
    "audit_patterns",
    "prompt_evals",
    "calibration_params",
    "llm_calls",
    "scan_schedules",
    "projects",
    "scans",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="确认执行删除")
    parser.add_argument("--keep-disk", action="store_true", help="保留工作区目录")
    args = parser.parse_args()
    if not args.yes:
        print("dry-run：加 --yes 才会删除")
        return 1

    from dotenv import load_dotenv

    load_dotenv()
    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.db.pool import get_conn

    ensure_control_schema()
    with get_conn() as conn, conn.cursor() as cur:
        for table in ANALYSIS_TABLES:
            cur.execute(f"SELECT count(*) FROM {table}")
            before = cur.fetchone()[0]
            cur.execute(f"DELETE FROM {table}")
            print(f"{table}: {before} -> 0")
        conn.commit()

    if not args.keep_disk:
        from codesentry.config import get_settings

        root = Path(get_settings().work_dir)
        for sub in ("deploy",):
            target = root / sub
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
                print(f"removed {target}")
        # work/ 下均为上传/克隆/报告临时目录；清空但保留 work 根
        if root.exists():
            for child in root.iterdir():
                if child.is_dir() and child.name not in ("tools",):
                    shutil.rmtree(child, ignore_errors=True)
                    print(f"removed {child}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
