"""M4 全链 bench（bench v2）：LangGraph 全链 vs EXPECT 标注统计。

逐样例文件建立「单文件微仓」分别跑 graph 全链——文件级真值对照：
- vulnerable 文件产出 ≥1 finding（triage 后）→ TP；0 → FN（漏报，红线）
- clean 文件产出 finding → FP（误报，降噪目标：越少越好）

输出 JSON 到 doc/m4-fullchain.json，摘要文本 meng ke report。
"""

from __future__ import annotations

import json
from pathlib import Path

import typer


def run_fullchain(
    root: str,
    out: str,
    *,
    session: str = "codesentry-fullchain",
    limit: int | None = None,
) -> dict:
    from pathlib import Path as PP

    import openai

    from codesentry.agents.llm import LLMClient
    from codesentry.agents.state import new_state
    from codesentry.agents.triage import run_triage
    from codesentry.bench import parse_expect
    from codesentry.engines.semgrep import run_semgrep

    llm = LLMClient.from_config()
    if "opencode" in llm.base_url:
        llm._client = openai.OpenAI(
            base_url=llm.base_url, api_key=llm.api_key,
            default_headers={"x-opencode-session": session},
        )

    rootp = PP(root)
    files = sorted(
        p for p in rootp.rglob("*")
        if p.is_file() and parse_expect(str(p)) in ("vulnerable", "clean")
    )
    if limit:
        files = files[:limit]

    tp = fp = fn = 0
    detail: dict[str, dict] = {}
    for p in files:
        exp = parse_expect(str(p))
        # 单文件微仓（semgrep 输出的 path 是相对 repo 的）
        res = run_semgrep(repo=str(rootp), config="rules/codesentry-core.yml")
        f_findings = [f for f in res.findings if str(p.name) in f.file or str(p).endswith(f.file)]
        # 证据：该文件源码
        src = p.read_text(encoding="utf-8", errors="replace").splitlines()
        st = new_state(str(rootp), OSS=False)
        st["engine_findings"] = [f.model_dump() for f in f_findings]
        st["evidence"] = {
            f"{f.rule_id}@{f.line}": {"code": src[:30]} for f in f_findings
        }
        out_tri = run_triage(st, llm=llm) if f_findings else {"triaged_findings": []}
        kept = out_tri["triaged_findings"]
        hit_llm = len(kept) > 0
        hit_engine = len(f_findings) > 0
        if exp == "vulnerable":
            if hit_llm:
                tp += 1
            else:
                fn += 1
        elif hit_llm:
            fp += 1
        detail[p.name] = {
            "expect": exp, "engine_hit": hit_engine, "llm_hit": hit_llm,
            "engine_count": len(f_findings), "llm_verdicts": [t["triage"]["verdict"] for t in kept],
        }

    result = {
        "root": str(rootp), "files": len(files), "tp": tp, "fp": fp, "fn": fn,
        "recall": tp / (tp + fn) if (tp + fn) else 0.0,
        "detail": detail,
        "tokens_used": llm.tokens_used,
    }
    Path(out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def fullchain_cmd(
    root: str = typer.Argument("bench/selfbuilt", help="样例根目录"),
    out: str = typer.Option("doc/m4-fullchain.json", "--out"),
    limit: int = typer.Option(0, "--limit", help="只跑前 N 个文件（0=全部）"),
) -> None:
    r = run_fullchain(root, out, limit=limit or None)
    typer.echo(
        f"fullchain bench: TP={r['tp']} FN={r['fn']} FP={r['fp']}"
        f" recall={r['recall']:.0%} tokens={r['tokens_used']} — {out}"
    )
