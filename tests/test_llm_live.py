"""LLM 通道冒烟（方案 B 第一步）。显式运行：uv run pytest -m live"""

import os

import pytest

pytestmark = [pytest.mark.live]


def test_llm_channel_live():
    os.environ.setdefault("CODESENTRY_DATABASE_URL", "postgresql://codesentry:devtest@127.0.0.1:5432/codesentry")
    from codesentry.agents.llm import LLMClient

    c = LLMClient.from_config()
    out = c.complete("You are a calculator. Reply with the number only.", "1+1=?", model_role="fast")
    assert out.strip().endswith("2"), out[:80]
    assert c.tokens_used > 0


def test_triage_fp_tp_live():
    """方案B 验收：显式误报被 reject/demote；真漏洞保持 keep。"""
    import openai

    from codesentry.agents.llm import LLMClient
    from codesentry.agents.triage import run_triage

    from_config = LLMClient.from_config()
    c = LLMClient(
        base_url=from_config.base_url,
        api_key=from_config.api_key,
        fast_model=from_config.fast_model,
        deep_model=from_config.deep_model,
    )
    c._client = openai.OpenAI(
        base_url=c.base_url, api_key=c.api_key,
        default_headers={"x-opencode-session": "codesentry-live-01"},
    ) if "opencode.ai" in c.base_url else c._client

    finding = {
        "rule_id": "python.flask.ssrf-requests", "cwe": 918, "severity": "high",
        "confidence": 0.7, "file": "app.py", "line": 3,
        "message": "requests.get with hardcoded URL", "engine": "semgrep",
    }
    fp_ev = {"code": [
        "import requests",
        "def fetch():",
        '    return requests.get("https://api.hardcoded.com/v1/ping", timeout=5)',
    ]}
    tp_ev = {"code": [
        "import requests",
        "from flask import request",
        "@app.route('/fetch')",
        "def fetch():",
        "    url = request.args.get('url')",
        "    return requests.get(url, timeout=5)",
    ]}
    key = "python.flask.ssrf-requests@3"
    out_fp = run_triage({"engine_findings": [finding], "evidence": {key: fp_ev}}, llm=c)
    out_tp = run_triage({"engine_findings": [finding],
                         "evidence": {key: tp_ev}}, llm=c)
    # 真漏洞：必须保留（零漏报）
    assert out_tp["triaged_findings"], "真漏洞被否决——漏报！"
    # 误报：应被降级或否决
    assert not out_fp["triaged_findings"] or out_fp["triaged_findings"][0]["triage"]["verdict"] != "keep" or \
        out_fp["triaged_findings"][0]["triage"]["confidence"] < 0.6, "误报未被降级"
