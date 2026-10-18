"""opencode zen 通道冒烟（渠道探针；live 显式 -m live）。

run: uv run pytest -m live tests/test_opencode_probe.py -q
"""

import pytest
import openai

pytestmark = pytest.mark.live

BASE = "https://opencode.ai/inference/go/openai/v1"
KEY = "oc_sk_11c63f526b23_k9neCKIDNYSkAuQ-ArfoqElPnd0Vd18A"


def _chat(model: str) -> dict:
    c = openai.OpenAI(api_key=KEY, base_url=BASE,
                      default_headers={"x-opencode-session": "codesentry-probe-001"})
    r = c.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "reply 7 only"}],
        max_tokens=300,
        temperature=0,
    )
    return r.model_dump()


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
            pytest.skip(f"region gating: {msg[:80]}")
        raise
