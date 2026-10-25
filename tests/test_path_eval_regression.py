import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from codesentry.agents.path_audit import run_path_audit
from codesentry.control.audit_paths import claim_paths, finish_path
from codesentry.db.pool import get_conn
from codesentry.rag.graph_build import build_graph
from codesentry.rag.graph_delta import apply_engine_hints
from codesentry.rag.path_build import build_paths

DATASET = Path(__file__).parent / "fixtures" / "path_eval.json"


def _cleanup(sid: int) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM audit_paths WHERE scan_id=%s", (sid,))
        cur.execute("DELETE FROM audit_rounds WHERE scan_id=%s", (sid,))
        conn.commit()


@pytest.mark.parametrize("case", json.loads(DATASET.read_text())["cases"])
def test_path_eval_dataset_offline(case, tmp_path, monkeypatch):
    repo = tmp_path / case["name"]
    for name, content in case["files"].items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    sid = 989000 + uuid.uuid4().int % 1000
    try:
        built = build_graph(str(repo), project=str(repo.resolve()))
        apply_engine_hints(str(repo), built["build_id"], [case["hint"]])
        build_paths(sid, str(repo.resolve()), built["build_id"], [case["hint"]])
        paths = claim_paths(sid, 1)
        if not paths:
            pytest.skip("no path built for case")
        verdict = case["expect_verdict"]
        payload = json.dumps({
            "verdict": verdict, "confidence": 0.9,
            "cwe": case["expect_cwe"], "severity": "high",
            "reason": "dataset expectation",
            "fix_advice": "validate input",
            "sanitized": verdict == "clean",
            "evidence": [{"file": case["hint"]["file"], "line": case["hint"]["line"],
                          "snippet": "..."}],
        }, ensure_ascii=False)
        monkeypatch.setattr("codesentry.agents.tools.run_tool_loop",
                            lambda *a, **k: (payload, []))
        runtime = SimpleNamespace(enabled=True, llm=object(),
                                  system=lambda: "path audit",
                                  max_iterations=2)
        result = run_path_audit({"repo_path": str(repo), "scan_id": sid,
                                 "engine_hints": [case["hint"]]},
                                paths[0], runtime=runtime)
        assert result["verdict"] == verdict
        assert int(result.get("cwe") or 0) == case["expect_cwe"]
        finish_path(paths[0]["id"], "finding" if verdict == "finding" else "clean",
                    result)
    finally:
        _cleanup(sid)
