"""Agent 基座真实 Provider 冒烟（需用户自行提供密钥）。

用法：
  export OPENCODE_GO_API_KEY='...'
  PYTHONPATH=src .venv/bin/python scripts/live_agent_smoke.py \
      --base-url https://opencode.ai/zen/go/v1 --model qwen3.8-flash

脚本不会打印或写入密钥；临时 Profile 在结束时删除。
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("OPENCODE_GO_BASE_URL", "https://opencode.ai/zen/go/v1"))
    parser.add_argument("--model", default=os.environ.get("OPENCODE_GO_MODEL", "qwen3.8-flash"))
    parser.add_argument("--agent", default="triage")
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--keep", action="store_true", help="保留临时 Profile 以便检查")
    args = parser.parse_args()

    key = os.environ.get("OPENCODE_GO_API_KEY", "")
    if not key:
        print("OPENCODE_GO_API_KEY not set", file=sys.stderr)
        return 2

    from codesentry.agents.runtime import prepare_agent
    from codesentry.agents.triage import triage_one
    from codesentry.control import agent_config, profiles
    from codesentry.db.pool import get_conn

    name = f"live-smoke-{uuid.uuid4().hex[:6]}"
    profile = profiles.create_profile(
        {
            "name": name,
            "provider": "opencode-go",
            "protocol": "openai-compatible",
            "base_url": args.base_url,
            "api_key": key,
            "fast_model": args.model,
            "deep_model": args.model,
            "max_tokens": args.max_tokens,
            "billing_mode": "subscription",
            "extra_headers": {"x-opencode-session": "${session_id}"},
        },
        actor="live-smoke",
    )
    if profile is None:
        print("profile create failed (name conflict or DB unavailable)", file=sys.stderr)
        return 1

    agent_config.ensure_agent_configs()
    try:
        with get_conn() as c, c.cursor() as cur:
            cur.execute(
                "UPDATE agent_configs SET llm_profile_id=%s WHERE name=%s",
                (profile.id, args.agent),
            )
            c.commit()
        rt = prepare_agent(args.agent, scan_id=0)
        print("bound_profile_id:", rt.profile_id)
        print("prompt_version:", rt.prompt_version, "fallback:", rt.prompt_fallback)
        print("skills:", [s.name for s in rt.skills])
        finding = {
            "rule_id": "live.ssrf", "cwe": 918, "severity": "HIGH", "confidence": 0.5,
            "file": "app.py", "line": 10, "message": "SSRF: user-controlled URL",
            "engine": "semgrep",
        }
        evidence = {"code": [{"path": "app.py", "snippet": "url = request.args['url']; requests.get(url)"}]}
        out = triage_one(rt.llm, finding, evidence, system=rt.system())
        print("triage_verdict:", out.get("verdict"), "confidence:", out.get("confidence"))
        print("rationale:", str(out.get("rationale") or "")[:200])
        print("last_meta:", rt.llm.last_meta)
        return 0
    finally:
        if not args.keep:
            with get_conn() as c, c.cursor() as cur:
                cur.execute(
                    "UPDATE agent_configs SET llm_profile_id=NULL WHERE name=%s", (args.agent,)
                )
                cur.execute("DELETE FROM llm_usage WHERE profile_id=%s", (profile.id,))
                cur.execute("DELETE FROM llm_profiles WHERE id=%s", (profile.id,))
                c.commit()
            print("cleanup: ok")


if __name__ == "__main__":
    raise SystemExit(main())
