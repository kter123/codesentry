"""OpenCode Go 通道冒烟（渠道探针；live 显式 -m live）。

密钥只从环境变量读取，缺失时整模块 skip。禁止在仓库中硬编码任何密钥。
run: OPENCODE_GO_API_KEY=... uv run pytest -m live tests/test_opencode_probe.py -q
"""

import os

import openai
import pytest

pytestmark = pytest.mark.live

BASE = os.environ.get("OPENCODE_GO_BASE_URL", "https://opencode.ai/zen/go/v1")
KEY = os.environ.get("OPENCODE_GO_API_KEY", "")

if not KEY:
    pytest.skip("OPENCODE_GO_API_KEY not set", allow_module_level=True)


def _chat(model: str) -> dict:
    c = openai.OpenAI(
        api_key=KEY,
        base_url=BASE,
        default_headers={"x-opencode-session": "codesentry-probe-001"},
    )
    r = c.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "reply 7 only"}],
        max_tokens=300,
        temperature=0,
    )
    return r.model_dump()


def test_glm53():
    d = _chat("glm-5.3")
    msg = d["choices"][0]["message"]
    assert msg.get("content") or msg.get("reasoning_content") or msg.get("reasoning")


def test_deepseek_v41_flash():
    try:
        d = _chat("deepseek-v4.1-flash")
        msg = d["choices"][0]["message"]
        assert msg.get("content") or msg.get("reasoning_content")
    except Exception as e:
        msg = str(e)
        if "Global regions" in msg or "unavailable" in msg.lower():
            pytest.skip(f"provider gating: {msg[:80]}")
        raise
