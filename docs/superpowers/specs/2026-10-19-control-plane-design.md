# CodeSentry 控制平面设计规格（需求 6 · 全量平台）

> 日期：2026-10-19。上游：用户选择「全量平台」档，并要求包含用量成本看板、Prompt A/B 与评测、Agent 能力矩阵与观测、配置审计与快照回放。技术栈：Vue 3 + FastAPI。本规格与 `2026-10-19-vue3-console-m6-design.md`（需求 1–5）并行实施，共用 `llm_profiles` 与 `agent_configs`。

## 1. 总体架构

```
Vue3 控制台 (Element Plus + Pinia + Vue Router + Vue Flow + ECharts + G6)
        │  /api  (JWT / API Token)
FastAPI 控制面
  ├─ auth        users / tenants / api_tokens / RBAC
  ├─ config      llm_profiles / agent_configs / prompts / skills / rules / graph_templates
  ├─ runtime     扫描执行、节点级 LLM 解析、prompt/skill 注入、能力门禁
  ├─ observability  llm_usage / node_runs / audit / health
  └─ delivery     CI token / webhook / SARIF / 配置导出导入
Postgres（业务 schema）+ LangGraph（业务 schema checkpoint）
```

两条硬原则：

1. **可复现**：每次扫描固定 `llm_profile_id + prompt_versions + skill_versions + rule_set + graph_template_version`，写入 `scans.*_snapshot` 与 `agent_artifacts`。
2. **可审计**：所有配置写操作进 `config_audit`，密钥只写不读（读接口永远掩码）。

## 1.5 LangGraph 运行时内核（至关重要）

控制面不自己实现编排语义，全部落在 LangGraph 原生能力上：

| LangGraph 能力 | 平台用法 |
|---|---|
| `StateGraph` + `TypedDict` 状态 | `AuditState` 为唯一事实源；控制台编排模板编译为 StateGraph |
| `add_conditional_edges` / `Command` | triage→retrieval 补查、deploy 失败→poc、失败重熔断 |
| `interrupt()` + `Command(resume=...)` | 人工复核队列；复核人决策回灌图中断点 |
| `PostgresSaver` checkpointer | 崩溃恢复、断点续跑、审计链基线 |
| `get_state_history` / `update_state` | 扫描时间旅行、节点回放、人工修正状态后继续 |
| `Send` API | 按 finding 并行 fan-out triage / PoC，替代串行循环 |
| `RetryPolicy` / `timeout` | 每个节点独立重试与超时，替代手写退避 |
| 子图（subgraph） | 每个 Agent 可注册为子图（含自己的工具循环），主图只依赖接口 |
| `astream(stream_mode=["updates","custom","values","messages"])` | WebSocket 实时推送节点开始/结束/token/中断事件 |
| `PostgresStore` / `BaseStore` | 长期记忆：历史 finding、KB、skill 检索；跨扫描复用 |
| `langgraph.json` + LangGraph Studio | 开发期可视化调试图；CI 快照回归 |
| `InMemorySaver` | 单测不依赖 Postgres |

**实现约束**

1. 节点函数保持 `state -> partial update`；副作用（DB、Docker、HTTP）只在节点内部，便于回放。
2. 所有节点经 `node_run` 遥测包装，产出 `node_runs` + `agent_artifacts`；artifacts 的 `prev_sha256` 链与 checkpoint 双轨，审计可交叉校验。
3. 人工复核使用 `interrupt()` 而不是轮询表；`/api/scans/{id}/resume` 即 `Command(resume=decisions)`。
4. 编排模板只允许调整节点启停、边与重试上限，不允许注入任意代码；未知节点拒绝编译。
5. 流式事件统一映射为 UI 事件：`node.start / node.end / llm.token / message / interrupt / error / done`。
6. 长任务默认 `durability="async"`；人工复核与 PoC 执行使用 `"sync"`，确保中断前落盘。

**新增模块**

```
src/codesentry/orchestrator/
  graph.py        模板 → StateGraph 编译（含 Send、子图、条件边）
  registry.py     节点注册表（agent 名 → 可调用对象 + 元数据）
  streaming.py    astream_events → WS 事件泵
  replay.py       get_state_history / update_state / 节点回放
  store.py        PostgresStore 长期记忆（KB、历史 finding、skills 索引）
```

**验收**

- 删除任一节点（除 recon/scan/report）后仍可编译并跑通，`node_runs` 标记 skipped；
- 人工复核中断后重启进程仍能 resume（checkpointer 生效）；
- `get_state_history` 能列出每次节点更新，UI 时间旅行可回到任一 checkpoint；
- triage 对 20 条 finding 使用 `Send` 并行，墙钟时间显著低于串行（记录对比）；
- WS 能收到完整事件序列，前端时间线不依赖轮询。


## 2. 身份、租户与权限

### 2.1 数据模型

```sql
CREATE TABLE tenants (
  id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, slug TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE users (
  id BIGSERIAL PRIMARY KEY, tenant_id BIGINT NOT NULL REFERENCES tenants(id),
  username TEXT NOT NULL, password_hash TEXT NOT NULL, display_name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'viewer',          -- admin|analyst|viewer
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_login_at TIMESTAMPTZ,
  UNIQUE (tenant_id, username)
);
CREATE TABLE api_tokens (
  id BIGSERIAL PRIMARY KEY, tenant_id BIGINT NOT NULL REFERENCES tenants(id),
  user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL, token_prefix TEXT NOT NULL, token_hash CHAR(64) NOT NULL UNIQUE,
  scopes JSONB NOT NULL DEFAULT '["scan:write","scan:read"]',
  expires_at TIMESTAMPTZ, last_used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- 现有表统一 `ADD COLUMN tenant_id BIGINT NOT NULL DEFAULT 1`：`scans / llm_profiles / prompts / skills / rule_sets / graph_templates / agent_configs`。
- 默认租户 `id=1, slug='default'`；首个 admin 由 `codesentry user create --admin` 或环境变量 `CODESENTRY_ADMIN_PASSWORD` 引导创建。
- 密码：`argon2`（或 bcrypt）；JWT（HS256，`CODESENTRY_SECRET_KEY`）存 HttpOnly Cookie，TTL 12h。
- API Token：`cs_<prefix>_<secret>`，仅创建时返回一次；库中存 SHA-256；scope 校验到端点。

### 2.2 角色矩阵

| 能力 | admin | analyst | viewer | ci token |
|---|---|---|---|---|
| 查看扫描/图/报告 | ✓ | ✓ | ✓ | ✓（scan:read） |
| 创建扫描、复核 | ✓ | ✓ | — | ✓（scan:write） |
| 配置 LLM/Agent/Prompt/Skill/Rule | ✓ | — | — | — |
| 用户/租户/Token 管理 | ✓ | — | — | — |
| 查看审计 | ✓ | ✓ | — | — |

### 2.3 API

`POST /api/auth/login`、`POST /api/auth/logout`、`GET /api/auth/me`；
`GET/POST/PUT/DELETE /api/users`、`/api/tenants`、`/api/api-tokens`（admin）；
`POST /api/api-tokens/{id}/revoke`。

## 3. LLM 管理

### 3.1 模型

```sql
CREATE TABLE llm_profiles (
  id BIGSERIAL PRIMARY KEY, tenant_id BIGINT NOT NULL DEFAULT 1,
  name TEXT NOT NULL, provider TEXT NOT NULL DEFAULT 'openai-compatible',
  base_url TEXT NOT NULL, api_key_cipher TEXT NOT NULL DEFAULT '',
  fast_model TEXT NOT NULL DEFAULT '', deep_model TEXT NOT NULL DEFAULT '',
  temperature REAL NOT NULL DEFAULT 0.0, max_tokens INT NOT NULL DEFAULT 0,
  timeout_s INT NOT NULL DEFAULT 60, max_concurrency INT NOT NULL DEFAULT 4,
  input_price_per_1k REAL NOT NULL DEFAULT 0, output_price_per_1k REAL NOT NULL DEFAULT 0,
  capabilities JSONB NOT NULL DEFAULT '{}',   -- {"json":true,"tools":false,"stream":true}
  fallback_profile_id BIGINT REFERENCES llm_profiles(id) ON DELETE SET NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE, is_default BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, name)
);
```

- `api_key_cipher`：Fernet（`CODESENTRY_SECRET_KEY` 派生）加密；读接口返回 `sk-xxxx…`；写接口空值=保留。
- 单租户仅一个 `is_default`（应用层事务内清空其他）。
- 被 agent 绑定的 profile 禁止删除（409），需先解绑。

### 3.2 路由与韧性

`LLMClient.for_agent(agent)` 解析顺序：

1. `agent_configs.llm_profile_id`（enabled）
2. profile 的 `fallback_profile_id`
3. `is_default`
4. 全局 `Settings`（`.env`）

失败策略：429/5xx/超时 → 指数退避重试 `retries` 次 → 切 fallback profile → 仍失败则节点降级（保留引擎原始结论）。预算层：`BudgetGuard` 进入 `warn`（80%）时 deep 模型自动降 fast（可关）；`breach` 时停止新 LLM 调用。

### 3.3 用量与成本

```sql
CREATE TABLE llm_usage (
  id BIGSERIAL PRIMARY KEY, tenant_id BIGINT NOT NULL DEFAULT 1,
  scan_id BIGINT, agent TEXT NOT NULL, profile_id BIGINT, model TEXT NOT NULL,
  prompt_tokens INT NOT NULL DEFAULT 0, completion_tokens INT NOT NULL DEFAULT 0,
  cost_usd REAL NOT NULL DEFAULT 0, latency_ms INT NOT NULL DEFAULT 0,
  ok BOOLEAN NOT NULL DEFAULT TRUE, error TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- 每次 `complete()` 写入；`cost = prompt/1000*input_price + completion/1000*output_price`。
- `GET /api/usage/summary?from&to&group_by=profile|agent|scan|day`；
- `GET /api/usage/quota` 返回当月 token/费用与阈值（`llm_quota_tokens`、`llm_quota_usd` 存 app_settings）。
- 超阈值仅告警（写 messages + UI 红点），不硬停，避免误伤扫描。

### 3.4 探测

`POST /api/llm-profiles/{id}/test`：最小 chat + 延迟；`POST .../probe`：拉 `/models`（兼容则返回列表）、JSON 模式探测、报告 capabilities。

## 4. Agent 管理与能力矩阵

```sql
ALTER TABLE agent_configs
  ADD COLUMN llm_profile_id BIGINT REFERENCES llm_profiles(id) ON DELETE SET NULL,
  ADD COLUMN display_name TEXT NOT NULL DEFAULT '',
  ADD COLUMN capabilities JSONB NOT NULL DEFAULT '{}',
  ADD COLUMN timeout_s INT NOT NULL DEFAULT 120,
  ADD COLUMN max_iterations INT NOT NULL DEFAULT 8,
  ADD COLUMN temperature_override REAL,
  ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
```

`capabilities` 默认值：

| agent | engines | network | shell | poc_exec |
|---|---|---|---|---|
| recon | [] | false | false | false |
| scan | semgrep,codeql,joern | false | true | false |
| retrieval | [] | false | false | false |
| triage | [] | false | false | false |
| poc_gen | [] | sandbox 时 true | sandbox 时 true | sandbox 时 true |
| report | [] | false | false | false |

- 运行时门禁：`scan` 只调度 allowlist 内引擎；`poc_gen` 非 `poc_exec` 时强制 `plausible`；`network=false` 时禁用 listener/外连。
- `enabled=false` → 节点跳过并记 `node_runs.status='skipped'`，链路继续。
- 观测：`GET /api/agents/{name}/stats?days=30` → 调用次数、成功率、P50/P95 耗时、token、verdict 分布。
- `POST /api/agents/{name}/dry-run`：传入样例 state，渲染最终 system prompt（含 skills）并返回，不落库、不调外部工具。
- `POST /api/agents/{name}/preview-prompt`：返回 prompt 版本 + skills 注入块 + 估算 token。

## 5. Prompt 管理

- `prompt_versions` 增 `body_sha256`、`tenant_id`；同一 agent 仅一条 `active=true`（激活时事务内切换）。
- API：列表 / 版本 / 新建 / 回滚 / 激活 / diff / lint / eval。
- **Lint**：长度上限、必须包含输出 JSON 结构说明、禁用危险指令（`rm -rf` 等）。
- **A/B**：`agent_configs.ab_json = {"a":3,"b":7,"ratio":0.5}`；扫描创建时按比例分配并写入 `scans.prompt_snapshot`；结果按版本聚合到 `prompt_evals`。
- **评测**：`POST /api/prompts/eval`，参数 `{agent, version, dataset: "selfbuilt"|"bmj_sample", limit}`；后台任务跑真实 LLM Triage，指标 `{recall, precision, fp_rate, fn, ece}` 存 `prompt_evals`；`GET /api/prompt-evals` 对比列表。

## 6. Skills 运营

```sql
ALTER TABLE skill_assignments
  ADD COLUMN version_pin INT,
  ADD COLUMN priority INT NOT NULL DEFAULT 100,
  ADD COLUMN tenant_id BIGINT NOT NULL DEFAULT 1;
```

- 上传：SKILL.md 或 zip（解压校验路径穿越）；frontmatter `name/description` 必填；版本自动 +1。
- 分配矩阵：agent × skill 勾选；支持 `version_pin`（空=跟随最新）、`priority`（升序注入）。
- 注入预览：`POST /api/skills/{name}/preview?agents=triage,poc_gen` 返回每个 agent 的注入块与估算 token。
- 超限：按 `skill_max_per` / `skill_max_total` 截断，告警进 `state.messages`。
- 使用追踪：`GET /api/skills/{name}/usage` → 引用该 skill 的扫描与版本。

## 7. 规则管理（沿用并增强）

- 列表 / 详情 / YAML 编辑 / `semgrep --validate` / 保存版本（`rule_sets`）/ 激活版本。
- 扫描创建时固定 `rule_set_version`；支持按租户配置默认规则集。
- 规则命中统计：`GET /api/rules/{id}/stats`（来自 findings 聚合）。

## 8. 可视化编排

```sql
CREATE TABLE graph_templates (
  id BIGSERIAL PRIMARY KEY, tenant_id BIGINT NOT NULL DEFAULT 1,
  name TEXT NOT NULL, version INT NOT NULL, config JSONB NOT NULL,
  active BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, name, version)
);
```

`config` 示例：

```json
{
  "nodes": [
    {"id": "recon", "enabled": true},
    {"id": "scan", "enabled": true},
    {"id": "retrieval", "enabled": true},
    {"id": "triage", "enabled": true},
    {"id": "deploy", "enabled": true},
    {"id": "poc_gen", "enabled": true},
    {"id": "report", "enabled": true}
  ],
  "edges": [
    {"from": "recon", "to": "scan"},
    {"from": "triage", "to": "retrieval", "when": "insufficient_evidence", "max": 3}
  ],
  "settings": {"human_review": false, "max_replans": 3}
}
```

- 校验：必须包含 `recon → scan → report`；只有 `triage→retrieval` 允许回边且带上限；节点必须在 `AGENT_NAMES ∪ {deploy, human_review}`。
- 运行时：`build_graph_from_template(config, agents)` 动态组图；扫描快照 `scans.graph_snapshot JSONB`。
- UI：Vue Flow 画布，左侧节点面板，右侧节点属性（agent/LLM/prompt/skills/超时），连线编辑，保存为新版本，设为默认。
- 安全阀：管理员可编辑；analyst 只读。

## 9. CI 集成与交付

- API Token scope：`scan:write`、`scan:read`、`report:read`。
- `POST /api/scans` 支持 `Authorization: Bearer cs_...`；`/api/scans/{id}/sarif` 下载 SARIF 2.1.0。
- webhook：`webhooks(id, tenant_id, url, secret, events JSONB, enabled)`；扫描完成/失败/复核完成时 POST，HMAC-SHA256 签名头 `X-CodeSentry-Signature`。
- CLI：`codesentry scan --fail-on high`，命中阈值返回非零；CI 示例写入 `docs/ci.md`。
- 配置包：`GET /api/config/export`（脱敏：不含 key）与 `POST /api/config/import?dry_run=true`（YAML/JSON，冲突策略 merge/replace）。

## 10. 审计、快照与回放

```sql
CREATE TABLE config_audit (
  id BIGSERIAL PRIMARY KEY, tenant_id BIGINT NOT NULL DEFAULT 1,
  actor TEXT NOT NULL, action TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
  before JSONB, after JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- 写操作统一经 `audit_write(actor, action, target, before, after)`；key 字段脱敏。
- `GET /api/audit?from&to&target_type&actor`（admin/analyst）。
- 扫描重放：`POST /api/scans/{id}/replay` 克隆源码（work 目录复用或重新 clone）+ 固定 snapshot 配置创建新扫描；`mode='replay'`。
- 节点重放：`POST /api/scans/{id}/replay-node/{node}` 用 `agent_artifacts.input_preview` 构造 state，只跑该节点，输出 diff 展示。

## 11. 健康与运维

`GET /api/health`：

```json
{"db": {"ok": true, "latency_ms": 3},
 "llm_profiles": [{"id": 1, "ok": true, "latency_ms": 420}],
 "embedding": {"ok": true, "dims": 1024},
 "docker": {"ok": true, "version": "27.x"},
 "engines": {"semgrep": "1.9x", "codeql": "2.x", "joern": "4.x"},
 "queue": {"running_scans": 1}}
```

- `POST /api/ops/docker/cleanup`：清理 `codesentry-target-*` 残留容器与未被引用镜像（需 admin + 二次确认参数）。
- `GET /api/ops/disk`：work 目录占用、可清理项。

## 12. Vue3 控制台页面

| 路由 | 页面 | 核心操作 |
|---|---|---|
| `/login` | 登录 | 用户名密码；Token 登录（CI 调试） |
| `/` | 总览 | 扫描趋势、token/费用、健康状态、待复核 |
| `/scans` | 扫描列表 | 上传 zip/git/diff、筛选、删除、重放 |
| `/scans/:id` | 扫描详情 | G6 调用链、源码切片、污点播放、部署状态、findings、审查链 |
| `/reviews` | 复核队列 | 决策、置信度四分量、resume |
| `/agents` | Agent 列表 | 启停、LLM 绑定、能力徽章、近 30 天指标 |
| `/agents/:name` | Agent 详情 | Prompt 版本、Skills 矩阵、能力矩阵、dry-run、观测图表 |
| `/llm` | LLM 管理 | CRUD、测试/探测、默认与 fallback、密钥轮换 |
| `/usage` | 用量成本 | 按 profile/agent/scan/日聚合图表、配额 |
| `/prompts` | Prompt 管理 | 版本 diff、编辑、激活、回滚、lint、A/B、评测 |
| `/skills` | Skills 管理 | 上传、版本、分配矩阵、注入预览、使用追踪 |
| `/rules` | 规则管理 | 列表、YAML 编辑、校验、版本、命中统计 |
| `/orchestration` | 可视化编排 | Vue Flow 画布、节点属性、保存/激活版本 |
| `/audit` | 审计 | 变更记录、before/after diff |
| `/settings` | 设置 | 全局兜底 LLM/embedding、配额、webhook、导入导出 |
| `/users` | 用户与 Token | 用户 CRUD、角色、API Token |

前端栈：Vue 3.5 + TypeScript + Vite + Vue Router + Pinia + Element Plus + Vue Flow + ECharts + AntV G6；
构建产物落 `src/codesentry/web/static/`，`base='/ui/'`。

## 13. 测试与验收

- 认证：登录/登出、JWT 过期、角色越权 403、CI token scope。
- 租户隔离：tenant A 看不到 tenant B 的扫描与配置。
- LLM：加密落库、掩码、默认唯一、fallback 切换、429 重试、预算降级、用量成本计算。
- Agent：绑定解析顺序、能力门禁（network=false 禁 listener）、disabled 跳过、dry-run 不落库。
- Prompt：激活唯一、回滚版本 +1、A/B 分流比例、lint、评测指标落库。
- Skills：版本锁定、优先级、Token 截断、批量分配、路径穿越防护。
- 编排：DAG 校验（缺节点/非法回边拒绝）、模板激活、按模板执行。
- 审计/回放：每次配置写有审计、导出不含密钥、replay 使用快照。
- CI：Bearer 创建扫描、SARIF 下载、webhook 签名校验。
- 健康：各子系统状态；Docker 清理仅 admin。

## 14. 里程碑（在 M6 沙箱/PoC 链路之外并行）

- **P1 身份与基础**：tenants/users/api_tokens/RBAC + 登录页 + 配置审计骨架
- **P2 LLM 控制面**：profiles（加密/掩码/默认/fallback）+ 路由与重试 + 用量表 + 成本看板
- **P3 Agent 控制面**：绑定 + 能力矩阵 + 观测 + dry-run + Prompt/Skill 运行时接线
- **P4 Prompt 闭环**：版本/激活/回滚/diff/lint/A-B/评测
- **P5 Skills 运营**：版本锁定/优先级/注入预览/批量分配/使用追踪
- **P6 编排与交付**：graph_templates + Vue Flow + CI token/SARIF/webhook + 导出导入
- **P7 控制台整合**：Vue3 全量页面 + 健康页 + 审计页 + 用户页

优先级：P1/P2/P3 为底座；P4/P5 依赖 P3 的运行时接线；P6/P7 最后。
