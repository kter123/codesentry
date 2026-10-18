# M4 前哨：Triage 降噪基线（方案B首个回测）

> 日期：2026-10-18。数据来源：本机真 LLM 全链测试（方案B doc/2026-10-18-plan-b-llm-triage-baseline.md 验收）。
> 通道：opencode go `glm-5.3-flash`（OpenAI 兼容，`https://opencode.ai/inference/go/openai/v1`，需 `x-opencode-session` 头）；温度 0。

## 结果

| 样例 | 引擎 finding | Triage 判定 | 结果 |
|---|---|---|---|
| b：显式误报（`requests.get("https://api.hardcoded.com")` 字面量 URL，CWE-918 high） | 1 | **reject** | ✅ 降噪出报告（-100%） |
| a：真漏洞（`request.args.get('url')` → `requests.get(url)`，CWE-918 high） | 1 | keep/demote（保守保留） | ✅ 零漏报 |

- 降噪率（单样例）：误报 1→0。满足成功标准 3「误报降 ≥50%」方向；样本量目前 n=2，正式 M4 双轨评测扩样。
- 漏报：0。
- 成本：2384 tokens / 2×triage 调用（glmm-5.3-flash，Go 渠道免费额度内）。
- 注意样例：真漏洞样例曾返回 `demote(0.55)`——demote 仍保留进报告，但要监控 demote 是否会降级后续 PoC 优先级（M4 扩样时统计）。

## 复现

```bash
# live 测试（默认 deselect，显式调用）：
uv run pytest tests/test_llm_live.py -m live -q
# .env 配置：CODESENTRY_MODEL_BASE_URL/Fast/Deep 指向 opencode go 通道
```

## agent.md §14 注记

M4 行基线数据来源：`doc/m4-triage-baseline.md`（方案B，2026-10-18，glm-5.3-flash 单样例 n=2）。
