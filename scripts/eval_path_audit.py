"""路径级审计评测：同一路径多轮运行，输出 verdict 分布与一致性。

用法：
    PYTHONPATH=src uv run python scripts/eval_path_audit.py --runs 3
    PYTHONPATH=src uv run python scripts/eval_path_audit.py --dataset tests/fixtures/path_eval.json --runs 3
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import uuid
from collections import Counter
from pathlib import Path


def _audit_case(name: str, files: dict, hint: dict, runs: int, keep: bool) -> dict:
    from codesentry.agents.path_audit import run_path_audit
    from codesentry.agents.runtime import prepare_agent
    from codesentry.agents.state import new_state
    from codesentry.control.audit_paths import claim_paths
    from codesentry.rag.graph_build import build_graph
    from codesentry.rag.graph_delta import apply_engine_hints
    from codesentry.rag.path_build import build_paths

    tmp = Path(tempfile.mkdtemp(prefix=f"cs-path-eval-{name}-"))
    for rel, content in files.items():
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8")
    sid = 990000 + uuid.uuid4().int % 1000
    try:
        built = build_graph(str(tmp), project=str(tmp.resolve()))
        apply_engine_hints(str(tmp), built["build_id"], [hint])
        build_paths(sid, str(tmp.resolve()), built["build_id"], [hint])
        paths = claim_paths(sid, 1)
        if not paths:
            return {"case": name, "error": "no path built"}
        state = new_state(str(tmp), OSS=False, scan_id=sid)
        state["graph_build_id"] = built["build_id"]
        state["graph_stats"] = built["stats"]
        state["engine_hints"] = [hint]
        runtime = prepare_agent("audit", scan_id=sid, with_llm=True)
        verdicts = []
        details = []
        for i in range(max(1, runs)):
            result = run_path_audit(state, paths[0], runtime=runtime)
            verdicts.append(str(result.get("verdict")))
            details.append({"run": i + 1, "verdict": result.get("verdict"),
                            "confidence": result.get("confidence"),
                            "reason": result.get("reason")})
        counts = Counter(verdicts)
        return {
            "case": name,
            "path_id": paths[0]["id"],
            "feasibility": paths[0].get("feasibility"),
            "distribution": dict(counts),
            "consistency": round(max(counts.values()) / len(verdicts), 3),
            "runs": details,
        }
    finally:
        try:
            from codesentry.db.pool import get_conn

            with get_conn() as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM audit_paths WHERE scan_id=%s", (sid,))
                cur.execute("DELETE FROM audit_rounds WHERE scan_id=%s", (sid,))
                conn.commit()
        except Exception:  # noqa: BLE001, S110
            pass
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--dataset", default="")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv()

    if args.dataset:
        data = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
        cases = data.get("cases") or []
        results = [_audit_case(str(c.get("name") or i), c.get("files") or {},
                               c.get("hint") or {}, args.runs, args.keep)
                   for i, c in enumerate(cases)]
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    tmp = Path(tempfile.mkdtemp(prefix="cs-path-eval-"))
    files = {
        "app.py": (
            "from flask import Flask, request\n"
            "app = Flask(__name__)\n"
            "@app.route('/run')\n"
            "def run():\n"
            "    cmd = request.args.get('cmd')\n"
            "    return eval(cmd)\n"
        )
    }
    hint = {"file": "app.py", "line": 6, "rule_id": "eval", "cwe": 95,
            "severity": "high", "message": "eval"}
    try:
        print(json.dumps(_audit_case("default", files, hint, args.runs, True),
                         ensure_ascii=False, indent=2))
    finally:
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
