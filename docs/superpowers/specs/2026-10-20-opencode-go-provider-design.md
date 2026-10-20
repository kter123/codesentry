# CodeSentry LLM Provider 设计规格：OpenCode Go 接入

> 日期：2026-10-20。上游需求：FR-20（LLM 管理）、FR-25（用量与成本）。本文档只描述 Provider 接入与协议适配，不包含任何真实密钥。

## 1. 结论摘要

| 项 | 实测结论 |
|---|---|
| Base URL | `https://opencode.ai/zen/go/v1` |
| 鉴权 | `Authorization: Bearer $OPENCODE_GO_API_KEY` |
| 模型目录 | `GET /models` 返回 OpenAI 风格列表，`id` **不带** `opencode-go/` 前缀 |
| OpenAI 兼容端点 | `POST /chat/completions` |
| Anthropic 兼容端点 | `POST /messages`（`x-api-key` + `anthropic-version`） |
| 必需请求头 | `x-opencode-session: <stable-session-id>`；缺失返回 `400 MissingSessionID` |
| 模型路由 | 不同模型支持不同协议；部分模型在 `/chat/completions` 返回 `400 ModelProtocolUnsupported` |
| 推理字段 | `reasoning_content`（OpenAI 风格）、`reasoning`、Anthropic `thinking` |
| 配额窗口 | 5 小时 $12 / 每周 $30 / 每月 $60；超出后可按 Zen 余额回退（取决于账户设置） |

**关键修正**：OpenCode 客户端示例中的 `opencode-go/` 前缀是客户端约定；直连原始 API 时应使用 `/models` 返回的 `id`。CodeSentry 的 Provider 适配层必须做前缀规范化，不能假定前缀存在。

## 2. 实测记录（2026-10-20）

| 请求 | 结果 |
|---|---|
| `GET /models` | `200`，返回约 34 个模型 |
| `POST /chat/completions`，无 session 头 | `400 MissingSessionID` |
| `POST /chat/completions`，`model=opencode-go/glm-5.3` | `400 Model is unavailable` |
| `POST /chat/completions`，`model=glm-5.3` + session | `200`，返回 `reasoning` 字段 |
| `POST /chat/completions`，`deepseek-v4.1-flash` | `200`，返回 `reasoning_content` |
| `POST /chat/completions`，`kimi-k3` / `minimax-m3` | `200`，推理型输出 |
| `POST /chat/completions`，`qwen3.8-flash` | `200`，正常 `content` |
| `POST /chat/completions`，`claude-haiku-5-5` / `gpt-6-luna` | `400 ModelProtocolUnsupported` |
| `POST /chat/completions`，`gemini-4-argon-contributor` | `400`，需在账户隐私设置允许训练数据 |
| `POST /messages`，`deepseek-v4-pro` | `200`，Anthropic 格式，含 `thinking` 块 |

注意：模型可用性会随账户权限、Workspace 隐私设置与上游状态变化，**不能写死**；必须通过探测与运行时错误分类动态维护。

## 3. Provider 预设数据模型

`llm_profiles` 扩展：

```sql
ALTER TABLE llm_profiles ADD COLUMN IF NOT EXISTS protocol TEXT NOT NULL DEFAULT 'openai-compatible';
ALTER TABLE llm_profiles ADD COLUMN IF NOT EXISTS extra_headers JSONB NOT NULL DEFAULT '{}';
ALTER TABLE llm_profiles ADD COLUMN IF NOT EXISTS quota_windows JSONB NOT NULL DEFAULT '[]';
ALTER TABLE llm_profiles ADD COLUMN IF NOT EXISTS model_catalog JSONB NOT NULL DEFAULT '[]';
ALTER TABLE llm_profiles ADD COLUMN IF NOT EXISTS model_protocols JSONB NOT NULL DEFAULT '{}';
ALTER TABLE llm_profiles ADD COLUMN IF NOT EXISTS billing_mode TEXT NOT NULL DEFAULT 'metered';
```

OpenCode Go 预设：

```json
{
  "name": "opencode-go",
  "provider": "opencode-go",
  "protocol": "openai-compatible",
  "base_url": "https://opencode.ai/zen/go/v1",
  "fast_model": "deepseek-v4.1-flash",
  "deep_model": "deepseek-v4-pro",
  "auth": {"type": "bearer", "env": "OPENCODE_GO_API_KEY"},
  "extra_headers": {"x-opencode-session": "${session_id}"},
  "model_prefix_policy": "strip",
  "model_protocols": {
    "deepseek-v4-pro": "anthropic-compatible",
    "claude-haiku-5-5": "anthropic-compatible",
    "gpt-6-luna": "anthropic-compatible"
  },
  "quota_windows": [
    {"window": "5h", "usd": 12},
    {"window": "week", "usd": 30},
    {"window": "month", "usd": 60}
  ],
  "billing_mode": "subscription",
  "input_price_per_1k": 0,
  "output_price_per_1k": 0
}
```

说明：

- `billing_mode=subscription` 时费用显示为 $0，但仍完整记录 token，用于配额与成本对比。
- `extra_headers` 中的 `${session_id}` 由运行时替换；禁止用户注入任意请求头，只允许白名单模板变量。
- `model_prefix_policy=strip`：若模型名包含 `/`，取最后一段并按 `model_catalog` 校验。

## 4. 调用方式

### 4.1 OpenAI 兼容

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["OPENCODE_GO_API_KEY"],
    base_url="https://opencode.ai/zen/go/v1",
    default_headers={"x-opencode-session": session_id},
)

resp = client.chat.completions.create(
    model="deepseek-v4.1-flash",
    messages=[{"role": "user", "content": prompt}],
    temperature=0,
)
```

### 4.2 Anthropic 兼容

```python
import os
from anthropic import Anthropic

client = Anthropic(
    api_key=os.environ["OPENCODE_GO_API_KEY"],
    base_url="https://opencode.ai/zen/go/v1",
    default_headers={"x-opencode-session": session_id},
)

resp = client.messages.create(
    model="deepseek-v4-pro",
    max_tokens=4096,
    messages=[{"role": "user", "content": prompt}],
)
```

### 4.3 Session ID

- 格式建议：`scan-{scan_id}-{agent}-{profile_id}`。
- 同一扫描内保持稳定，便于上游路由与前缀缓存。
- 不得包含用户名、密钥或代码内容。

## 5. 协议解析与错误分类

运行时解析顺序：

1. `model_protocols[model]`（逐模型覆盖）
2. Profile `protocol`
3. 默认 `openai-compatible`

错误分类：

| 错误 | 分类 | 处理 |
|---|---|---|
| `400 MissingSessionID` | 配置错误 | 立即补 session 头；不重试 |
| `400 ModelProtocolUnsupported` | 协议不匹配 | 切换另一协议尝试一次；仍失败标记模型不可用 |
| `400 Model is unavailable` | 模型不可用 | 切 fallback 模型/Profile；记录探测结果 |
| `429` / `5xx` / 超时 | 瞬时错误 | 指数退避 + fallback |
| 隐私设置限制 | 权限错误 | 标记不可用并提示原因；不自动修改账户设置 |

## 6. 推理型模型处理

- 统一解析 `content`、`reasoning_content`、`reasoning`、Anthropic `thinking`。
- 推理内容只用于调试视图，不写入审计报告正文。
- reasoning tokens 计入 `completion_tokens` 与预算。
- `finish_reason=length` 且 `content` 为空时：提高 `max_tokens` 重试一次，再降级 fallback。
- 对 Triage/PoC 这类要求结构化 JSON 的调用，优先选择支持 JSON 模式的非推理模型；推理模型需在 Prompt 中明确输出契约。

## 7. 配额与用量

- `quota_windows` 由 Provider 配置，平台按窗口聚合 `llm_usage`。
- 80% 告警，100% 可配置硬停；`billing_mode=subscription` 时仍统计 token。
- `GET /api/usage/quota?profile_id=` 返回每个窗口的已用/上限/重置时间。
- Zen 余额回退属于 Provider 侧行为，平台只在错误信息中呈现，不代为扣费。

## 8. 安全要求

1. 密钥只来自环境变量或加密后的 `llm_profiles.api_key_cipher`；**禁止**写入代码、文档、测试夹具、日志。
2. 读接口只返回前 8 位 + `…`；导出配置时移除密钥。
3. `extra_headers` 只允许白名单键与模板变量，防止 SSRF/头注入。
4. 请求与响应日志脱敏；不记录完整 Prompt 中的密钥/凭证。
5. 任何出现在对话、工单或截图中的密钥都应视为已泄露，使用后立即轮换。

## 9. 验收

- 创建 OpenCode Go Profile，`POST /llm-profiles/{id}/test` 返回成功。
- `probe` 能拉取 `/models` 并标记每个模型的协议与可用性。
- `deepseek-v4-pro` 自动走 `/messages`；`qwen3.8-flash` 走 `/chat/completions`。
- 缺少 `x-opencode-session` 时被分类为配置错误并给出明确提示。
- 推理模型输出可解析，reasoning 不进入报告正文。
- 配额窗口聚合正确，80% 告警触发。
- 日志、审计、导出中均无完整密钥。

## 10. 里程碑

- M6.1（FR-20）：Provider 预设、协议解析、探测、配额。
- M6.6/M6.7（FR-25）：配额看板与告警。
