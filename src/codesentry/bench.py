"""M4 质量评测 harness（agent.md §9 M4）：自建样例仓回归 + 统计。

样例文件首行/头注释 `EXPECT: vulnerable|clean`；harness 对样本目录跑引擎Rules
（当前 semgrep 单引擎口径），逐文件对照标注统计 TP/FP/FN，汇总输出报告 dict。
"""

import json
import os
from pathlib import Path

import typer

from codesentry.models import Finding


def parse_expect(path: str) -> str:
    """读文件头注释的 EXPECT 标注：vulnerable / clean；缺失或不可读标 unknown。"""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "unknown"
    head = text[:512]
    if "EXPECT:" not in head:
        return "unknown"
    m = head.split("EXPECT:", 1)[1].strip()
    token = (m.split()[0].lstrip("|").strip().lower()) if m else ""
    if token.startswith("vuln"):
        return "vulnerable"
    if token.startswith("clean"):
        return "clean"
    return "unknown"


def _expected_files(root: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for base, _dirs, files in os.walk(root):
        for name in files:
            p = os.path.join(base, name)
            exp = parse_expect(p)
            if exp in ("vulnerable", "clean"):
                out[p] = exp
    return out


def _hit_files(findings: list[Finding]) -> set[str]:
    return {os.path.abspath(f.file) for f in findings}


def run_selfbuilt(
    root: str,
    *,
    config: str,
    semgrep_bin: str = "semgrep",
) -> dict:
    """跑一个样例仓目录：引擎 findings × EXPECT 标注 → 统计。

    口径（M4 v1，semgrep-findings 粒度 = 文件级锈定）：
    - vulnerable 文件被命中 → TP；未命中 → FN（漏报）
    - clean 文件被命中 → FP（误报，计入降噪基准分母）
    """
    from codesentry.engines.semgrep import run_semgrep

    res = run_semgrep(repo=root, config=config, semgrep_bin=semgrep_bin)
    if res.status != "ok":
        return {"status": res.status, "reason": res.reason, "tp": 0, "fp": 0, "fn": 0, "clear": {}}

    hits = _hit_files(res.findings)
    expected = _expected_files(root)

    tp = sum(1 for p, e in expected.items() if e == "vulnerable" and os.path.abspath(p) in hits)
    fn = sum(1 for p, e in expected.items() if e == "vulnerable" and os.path.abspath(p) not in hits)
    fp = sum(1 for p, e in expected.items() if e == "clean" and os.path.abspath(p) in hits)
    return {
        "status": "ok",
        "engine_status": res.status,
        "total_expected": len(expected),
        "vulnerable": sum(1 for e in expected.values() if e == "vulnerable"),
        "clean": sum(1 for e in expected.values() if e == "clean"),
        "tp": tp,
        "fn": fn,
        "fp": fp,
        "recall": tp / (tp + fn) if (tp + fn) else 0.0,
        "hits": sorted(hits),
        "expected": expected,
    }


def write_report(stats: dict, out: str) -> None:
    Path(out).write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")


def bench_cmd(
    root: str = typer.Argument("bench/selfbuilt", help="样例仓根目录"),
    config: str = typer.Option("rules/codesentry-core.yml", "--config", help="semgrep 规则集"),
    out: str = typer.Option("doc/m4-selfbuilt.json", "--out", help="结果 json 输出路径"),
) -> None:
    st = run_selfbuilt(root, config=config)
    write_report(st, out)
    typer.echo(
        f"bench: TP={st['tp']} FN={st['fn']} FP={st['fp']}"
        f"（vulnerable={st.get('vulnerable', 0)} clean={st.get('clean', 0)}）"
        f" recall={st.get('recall', 0):.0%} — {out}"
    )
    if st.get("status") != "ok":
        raise typer.Exit(1)
    raise typer.Exit(0)
