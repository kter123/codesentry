"""opencode zen 通道冒烟（渠道探针；非 CI 依赖）。

run: uv run pytest tests/test_opencode_probe.py -q -s
"""

import json
import os
import urllib.request

import pytest

pytestmark = pytest.mark.live

BASE = "https://opencode.ai/inference/go/openai/v1"
KEY = "oc_sk_11c63f526b23_k9neCKIDNYSkAuQ-ArfoqElPnd0Vd18A"
UA = "codesentry/0.1"
SESSION = "codesentry-probe-001"


def _chat(model: str) -> dict:
    req = urllib.request.Request(
        f"{BASE}/chat/completions",
        data=json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": "reply 7 only"}],
            "max_tokens": 300,
            "temperature": 0,
        }).encode(),
        headers={
            "Content-Type": "application/json",
            "User-Agent": UA,
            "x-opencode-session": SESSION,
            "Authorization": f"Bearer {KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read())


def test_glm53_flash():
    d = _chat("glm-5.3-flash")
    msg = d["choices"][0]["message"]
    assert msg.get("content") or msg.get("reasoning_content")


def test_deepseek_v41_flash():
    try:
        d = _chat("deepseek-v4.1-flash")
        assert d["choices"][0]["message"].get("content")
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "Global regions" in msg:
            import pytest

            pytest.skip(f"region gating: {msg[:80]}")
        raise
