"""M4 bench harness 单测（样例 EXPECT 解析与统计口径）。"""

from pathlib import Path

from codesentry.bench import parse_expect, run_selfbuilt

ROOT = Path(__file__).resolve().parent.parent


def test_parse_expect_markers():
    v = ROOT / "bench/selfbuilt/python/vuln_sqli.py"
    c = ROOT / "bench/selfbuilt/python/safe_sqli.py"
    assert parse_expect(str(v)) == "vulnerable"
    assert parse_expect(str(c)) == "clean"
    assert parse_expect("/nonexistent/x.py") == "unknown"


def test_selfbuilt_full_recall_zero_fp():
    st = run_selfbuilt(str(ROOT / "bench/selfbuilt"), config=str(ROOT / "rules/codesentry-core.yml"))
    assert st["status"] == "ok", st
    assert st["vulnerable"] >= 5  # 六语言真漏洞样例下限（M4 收口前补齐）
    assert st["tp"] == st["vulnerable"], f"漏报 {st['fn']} 个"
    # clean 误报口径：允许历史 FP 但 M4 目标 0
    assert st["fp"] == 0, f"clean 样例被命中：{st.get('hits')}"
    assert st["recall"] >= 0.9
