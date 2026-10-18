import pytest

from codesentry.agents.skills import Skill, build_context_block, cap_body, parse_skill_md

SKILL_MD = """---
name: java-ssrf-audit
description: Java SSRF 链路审计要点
---

审计 Java SSRF 时检查 HttpClient/RestTemplate 的 URL 是否用户可控。

@ref:refs/sinks.md
"""


def test_parse_skill_md():
    s = parse_skill_md(SKILL_MD)
    assert s.name == "java-ssrf-audit"
    assert "RestTemplate" in s.body
    assert s.references == ["refs/sinks.md"]


def test_parse_requires_frontmatter():
    with pytest.raises(ValueError, match="frontmatter"):
        parse_skill_md("no frontmatter")


def test_cap_body_over_limit():
    body = "x" * 40000  # 10000 tokens 估
    capped, truncated = cap_body(body, max_per=8192)
    assert truncated and len(capped) == 8192 * 4


def test_cap_body_within():
    capped, truncated = cap_body("short")
    assert truncated is False and capped == "short"


def test_build_context_block_caps_and_warns():
    big = Skill(name="big", description="", body="y" * 40000, body_tokens_est=10000)
    small = Skill(name="small", description="", body="s" * 100, body_tokens_est=25)
    block, warnings = build_context_block([big, small])
    assert "big" in block and "small" in block
    assert any("超 8192" in w for w in warnings)


def test_total_cap_warns():
    big1 = Skill(name="b1", description="", body="y" * 40000, body_tokens_est=20000)
    big2 = Skill(name="b2", description="", body="z" * 40000, body_tokens_est=20000)
    _block, warnings = build_context_block([big1, big2], max_total=32768)
    assert any("总量上限" in w for w in warnings)
