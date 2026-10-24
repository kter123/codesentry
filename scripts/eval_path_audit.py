"""路径级审计评测：同一路径多轮运行，输出 verdict 分布与一致性。

用法：
    PYTHONPATH=src uv run python scripts/eval_path_audit.py --runs 3
"""

from __future__ import annotations

import argparse
import tempfile
import uuid
from collections import Counter
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv()
    from codesentry.agents.path_audit import run_path_audit
    from codesentry.agents.runtime import prepare_agent
    from codesentry.agents.state import new_state
    from codesentry.control.audit_paths import claim_paths
    from codesentry.rag.graph_build import build_graph
    from codesentry.rag.path_build import build_paths

    tmp = Path(tempfile.mkdtemp(prefix="cs-path-eval-"))
    (tmp / "app.py").write_text(
        "from flask import Flask, request\n"
        "app = Flask(__name__)\n"
        "@app.route('/run')\n"
        "def run():\n"
        "    cmd = request.args.get('cmd')\n"
        "    return eval(cmd)\n",
        encoding="utf-8",
    )
    sid = 990000 + uuid.uuid4().int % 1000
    built = build_graph(str(tmp), project=str(tmp.resolve()))
    build_paths(sid, str(tmp.resolve()), built["build_id"],
                [{"file": "app.py", "line": 6, "rule_id": "eval", "cwe": 95,
                  "severity": "high", "message": "eval"}])
    paths = claim_paths(sid, 1)
    if not paths:
        print("no path built")
        return 1
    path = paths[0]
    state = new_state(str(tmp), OSS=False, scan_id=sid)
    state["graph_build_id"] = built["build_id"]
    state["graph_stats"] = built["stats"]
    state["engine_hints"] = []
    runtime = prepare_agent("audit", scan_id=sid, with_llm=True)
    verdicts = []
    for i in range(max(1, args.runs)):
        result = run_path_audit(state, path, runtime=runtime)
        verdicts.append(str(result.get("verdict")))
        print(f"run {i + 1}: {result.get('verdict')} confidence={result.get('confidence')}")
    counts = Counter(verdicts)
    print("distribution:", dict(counts))
    print("consistency:", round(max(counts.values()) / len(verdicts), 3))
    if not args.keep:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
