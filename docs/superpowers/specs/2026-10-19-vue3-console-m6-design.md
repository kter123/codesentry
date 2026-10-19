# CodeSentry M6 设计规格：Vue3 控制台 + 沙箱部署 + PoC 实证 + 审查链 + 置信度

> 日期：2026-10-19。上游需求：①zip 上传后沙箱 agent 用 Docker 部署环境；②PoC 拿 shell 需实证验证；③PoC 审查链可反向追溯各 agent 的工作内容；④LLM 置信度模型；⑤SPA 白屏修复；⑥agent / LLM / prompt / skills 管理，agent 可绑定 LLM、prompt 与 skills；整体技术栈 Vue3 + FastAPI。

## 1. 技术栈决策

| 层 | 选型 | 说明 |
|---|---|---|
| 前端 | Vue 3.5 + TypeScript + Vite + Vue Router + Pinia | 全量替换现有 React 18 |
| UI | Element Plus | 管理后台表格/表单/树/抽屉最成熟 |
| 图可视化 | AntV G6 v5（框架无关） | 沿用现有图数据接口 |
| 后端 | FastAPI（不变） | 现有 API 全部保留，前缀 `/api` |
| 构建产物 | `src/codesentry/web/static/` | `base: '/ui/'`，FastAPI 托管 |

React 代码在 `web/frontend/` 原地重写；后端 API 契约不变，仅新增字段/端点。

## 2. 信息架构

侧栏一级导航：

1. **扫描** `/scans`：上传（zip / git / diff）、历史列表、状态
2. **图审阅** `/scans/:id`：调用链 G6、节点源码切片、污点播放器、部署状态、findings 表
3. **复核队列** `/reviews`：待人工复核扫描、finding 决策、置信度分解
4. **Agent 管理** `/agents`：6 节点卡片，绑定 LLM / Prompt / Skills / 预算 / 启停
5. **LLM 管理** `/llm`：多 LLM 配置 CRUD、连通性测试、默认标记
6. **Prompt 管理** `/prompts`：版本列表、编辑、回滚、激活
7. **Skills 管理** `/skills`：SKILL.md 上传、版本、按 agent 分配矩阵
8. **规则管理** `/rules`：规则列表、YAML 编辑、semgrep 校验、保存版本
9. **设置** `/settings`：全局兜底 LLM 与 embedding

## 3. LLM 配置管理

### 3.1 数据模型

```sql
CREATE TABLE IF NOT EXISTS codesentry.llm_profiles (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL DEFAULT 'openai-compatible',
    base_url TEXT NOT NULL,
    api_key TEXT NOT NULL DEFAULT '',      -- 只在服务端使用；读接口掩码
    fast_model TEXT NOT NULL DEFAULT '',
    deep_model TEXT NOT NULL DEFAULT '',
    temperature REAL NOT NULL DEFAULT 0.0,
    max_tokens INT NOT NULL DEFAULT 0,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE codesentry.agent_configs
    ADD COLUMN IF NOT EXISTS llm_profile_id BIGINT REFERENCES codesentry.llm_profiles(id) ON DELETE SET NULL;
ALTER TABLE codesentry.agent_configs
    ADD COLUMN IF NOT EXISTS display_name TEXT NOT NULL DEFAULT '';
ALTER TABLE codesentry.agent_configs
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
```

约束：`api_key` 读接口只返回前 8 位 + `…`；日志/报告永不输出。默认 LLM 只能有一个（应用层保证：设 default 时清空其他行）。

### 3.2 API

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/api/llm-profiles` | 列表（key 掩码、标出 default/被哪些 agent 绑定） |
| POST | `/api/llm-profiles` | 新建 |
| PUT | `/api/llm-profiles/{id}` | 更新；`api_key` 传入省略/空串表示保留原值 |
| DELETE | `/api/llm-profiles/{id}` | 删除；被 agent 绑定的行禁止删除（409） |
| POST | `/api/llm-profiles/{id}/test` | 用该配置发一次最小 chat 请求 |
| GET/PUT | `/api/agents/{name}` | 读/写 enabled、model_role、llm_profile_id、budget_override |
| GET | `/api/agents/{name}/skills` | 该 agent 生效 skills（含版本、sha、启用态） |
| GET | `/api/agents/{name}/prompt` | 当前激活 prompt + 版本 |

### 3.3 运行时解析

`LLMClient.for_agent(agent, role)`：

1. 查 `agent_configs.llm_profile_id` → `llm_profiles`（enabled 才行）；
2. 无绑定或不可用 → `is_default=true` 的 profile；
3. 再无 → 全局 `Settings`（`.env`）；
4. 全无 → `LLMError`，节点按 §10 容错降级。

`agent_configs.enabled=false` 时该节点抛 `AgentDisabled`，图层记为 `skipped`，链路继续。

## 4. Agent 管理

页面每个 agent 一张卡，展示并编辑：

- 启停开关（`agent_configs.enabled`）
- LLM 绑定下拉（`llm_profiles`）+ 角色（fast/deep）
- Prompt：当前版本摘要 + 跳转 Prompt 页
- Skills：已分配列表与开关（写 `skill_assignments`）
- 预算覆盖 JSON（`budget_override`）
- 运行态：最近扫描的耗时 / tokens / 状态（`node_runs`）

**运行时接线**（当前缺失，M6 必做）：

- `run_triage` / `gen_poc` / `run_recon` / `run_report` / `run_retrieval` 的 system prompt 改为
  `load_prompt(agent)` + `skills_for_agent(agent)` 注入块；
- 生效版本写入 `state.prompt_versions[agent]`，skills 写入 `state.skills_snapshot[agent]`；
- 扫描创建时把两者快照进 `scans.prompt_snapshot` / `scans.skill_snapshot`（已有列）。

## 5. Prompt 管理

- `prompt_versions` 维持现结构；新增激活语义：同一 agent 仅一条 `active=true`。
- API：列表 / 版本详情 / 新建版本（自动 +1）/ 回滚（复制旧 body 为新版本）/ 激活指定版本。
- 运行时 `load_prompt` 已实现 DB 回退种子，补齐「激活指定版本」端点即可。
- 保存时记录 `body_sha256`（新增列，冗余但便于审查链校验）。

## 6. Skills 管理

- 上传：解析 SKILL.md frontmatter（`name` / `description`），正文入库 `skill_versions`。
- 分配：`skill_assignments(skill_name, agent, enabled)` 矩阵，前端勾选。
- 运行时：`skills_for_agent(agent)` = enabled assignments ⋈ 最新 `skill_versions` ⋈ `skills.enabled`，
  经 `build_context_block` 按 `skill_max_per` / `skill_max_total` 截断注入；告警进 `state.messages`。
- 版本固定在扫描开始时，写入快照，保证可复现。

## 7. 规则管理

沿用现有 `/api/rules*`，Vue3 页面重做：列表、详情、YAML 编辑（CodeMirror 6 轻量接入或 textarea）、
`POST /api/rules/validate` 校验、`POST /api/rules/save` 落 `rule_sets` + 写回 `rules/codesentry-core.yml`。

## 8. M6.1 DeployAgent（Docker 沙箱）

**图**：`recon → scan → retrieval → triage → deploy → poc_gen → [human_review] → report`。

**行为**：

1. 语言探测复用 `detect_languages`；按语言取内置配方：
   - python：`requirements.txt` → `pip install -r`（预算内）；入口 `manage.py|app.py|main.py` 且含 uvicorn/gunicorn/flask → 起服务；否则 `python -m http.server` 仅作文件宿主，不标 ready
   - php：`php -S 0.0.0.0:8080 -t {root}`
   - js：`package.json` → `npm ci --omit=dev`（>120s 跳过）→ `npm start`
   - java：`pom.xml` → `mvn -q package -DskipTests`（>300s 降级）→ 找 jar 启动
   - go/c：`disabled` + 原因
2. Docker SDK：容器 `codesentry-target-{scan_id}`，网络 `codesentry-net-{scan_id}`，CPU=1、内存=512MB、
   宿主随机端口映射；工作目录只读挂载上传源码（`/target:ro`）。
3. 健康探测：容器内 HTTP GET `/`（或配置路径），60s 内 200 → `ready`；否则 `degraded`。
4. 失败/无 Docker → `disabled` + `deploy_log` 落因，链路继续（PoC 只能 `plausible`）。
5. `CODESENTRY_POC_RUN=off`（默认）→ 只构建镜像/容器不启动服务，状态 `built`（遵守 D28/D32）。

**Schema**：

```sql
ALTER TABLE scans ADD COLUMN IF NOT EXISTS deploy_status TEXT NOT NULL DEFAULT '';
ALTER TABLE scans ADD COLUMN IF NOT EXISTS deploy_log TEXT NOT NULL DEFAULT '';
ALTER TABLE scans ADD COLUMN IF NOT EXISTS target_url TEXT NOT NULL DEFAULT '';
```

**配置**：`CODESENTRY_DEPLOY_TIMEOUT_S`（默认 120）、`CODESENTRY_DEPLOY_MEM_MB`（512）、`CODESENTRY_DEPLOY_CPU`（1.0）。

## 9. M6.2 PoC 实证验证（canary）

「verified」必须附实证记录，LLM 自述不算。

1. **命令回显**：注入 `echo CODESENTRY-{nonce}`，执行输出含 nonce → `confirmed`（method=canary）
2. **HTTP 反连**：宿主 `127.0.0.1` 随机端口一次性 listener，路径 `/{nonce}`；目标回调命中 → `confirmed`（method=listener）
3. **文件副作用**：`touch /tmp/{nonce}` 后 `docker exec` 检查 → `confirmed`（method=fs-effect）
4. 无法实证（无 target / 网络禁）→ `plausible`；PoC 执行失败/被安全策略拒绝 → `rejected`

**执行边界**：只在 `docker exec codesentry-target-{scan_id}` 或 target 容器内；宿主不留目标进程；
listener 仅绑 127.0.0.1 且扫描结束即关；危险 payload 静态检查保留。

**Schema**：

```sql
ALTER TABLE findings ADD COLUMN IF NOT EXISTS verification_method TEXT NOT NULL DEFAULT '';
ALTER TABLE findings ADD COLUMN IF NOT EXISTS verification_nonce TEXT NOT NULL DEFAULT '';
ALTER TABLE findings ADD COLUMN IF NOT EXISTS confidence_parts JSONB NOT NULL DEFAULT '{}';
```

## 10. M6.3 Agent Artifacts 审查链

```sql
CREATE TABLE IF NOT EXISTS codesentry.agent_artifacts (
    id BIGSERIAL PRIMARY KEY,
    scan_id BIGINT NOT NULL REFERENCES codesentry.scans(id),
    seq INT NOT NULL,
    node TEXT NOT NULL,
    input_preview TEXT NOT NULL DEFAULT '',
    output_preview TEXT NOT NULL DEFAULT '',
    input_digest CHAR(64) NOT NULL,
    output_digest CHAR(64) NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    tokens INT NOT NULL DEFAULT 0,
    prev_sha256 CHAR(64) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scan_id, seq)
);
```

- `graph._wrap` 外包一层 artifact 捕获：input=与本节点相关的 state 摘要（≤4KB），output=node update 摘要（≤4KB）；
- `prev_sha256` = 上一条 `output_digest`，形成哈希链；
- API：`GET /api/scans/{id}/artifacts`、`GET /api/scans/{id}/artifacts/verify`（校验链连贯）；
- UI：finding 详情「审查链」tab，从 report 反向展示 deploy/poc_gen/triage/retrieval/scan/recon，每卡可展开全文。

## 11. M6.4 LLM 置信度校准

**四层模型**：`final = verdict_gated( min(raw, evidence, calibrated) )`

1. `raw`：LLM 自报 0–1
2. `evidence`：证据切片相似度（bge-m3 余弦，≥0.5 计满）+ 污点 BFS 实链存在加分；仅断言 −0.2
3. `calibrated`：温度缩放 `sigmoid(a*logit(raw)+b)`，参数拟合自 BMJ 抽样 + 自建集 + 人工复核结果
4. `verdict_gated`：`confirmed=1.0`、`rejected=0.1`，其余取前三者最小

```sql
CREATE TABLE IF NOT EXISTS codesentry.calibration_params (
    id BIGSERIAL PRIMARY KEY,
    fit_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    a REAL NOT NULL,
    b REAL NOT NULL,
    ece REAL NOT NULL DEFAULT 0
);
```

- `POST /api/calibration/fit` 重拟合并写库；`GET /api/calibration` 读最新参数与 ECE；
- `findings.confidence_parts` 存四分量；UI badge tooltip 分解展示；
- 验收：M4 数据集上 ECE ≤ 0.1，并记录校准前基线。

## 12. 前端工程

```
web/frontend/
  package.json        vue, vue-router, pinia, element-plus, @antv/g6, vite, typescript
  vite.config.ts      base '/ui/', proxy /api /ws, build.outDir ../src/codesentry/web/static
  src/main.ts         createApp + router + pinia + ElementPlus
  src/App.vue         侧栏布局
  src/api/client.ts    fetch 封装（错误 toast、类型）
  src/stores/scan.ts   扫描轮询 / WS
  src/router.ts       9 个页面路由
  src/pages/ScansPage.vue / ScanDetailPage.vue / ReviewsPage.vue
  src/pages/AgentsPage.vue / LlmProfilesPage.vue / PromptsPage.vue
  src/pages/SkillsPage.vue / RulesPage.vue / SettingsPage.vue
  src/components/GraphView.vue / NodeDrawer.vue / ConfidenceBadge.vue
  src/components/ArtifactChain.vue / DeployStatusCard.vue / SkillMatrix.vue
```

**SPA 路由**：后端 catch-all 已覆盖 `/`、`/ui/*` 与一级段；Vue Router 用 history 模式。

## 13. 测试与验收

- 后端单测：llm profile CRUD + 掩码 + 绑定解析、agent 配置读写、skills 注入截断、prompt 激活/回滚、canary 三协议（mock）、artifact 哈希链校验、置信度四层与 ECE。
- 前端：`npm run build` 通过；Playwright 冒烟（可选）覆盖 9 个路由 200 + 关键表单提交。
- M6 验收：
  1. 上传含 `requirements.txt + app.py` 的 zip → `deploy_status=ready`（poc_run=off 时 `built`），`target_url` 非空
  2. 自建 RCE 样例 → `verification_method=canary`，`execution_log` 含 nonce 命中
  3. 任一 confirmed finding 可展开全链 artifacts，`/artifacts/verify` 通过
  4. 拟合后 M4 集 ECE 数字入报告，UI badge 展示四分量
  5. 九个前端路由直接访问均 200 且无白屏

## 14. 里程碑

- **M6.0** 本规格 + 现有 SPA 修复入库
- **M6.1** LLM 管理 + Agent 绑定 + Prompt/Skills 运行时接线（需求 6 的后端）
- **M6.2** DeployAgent + Docker 沙箱（需求 1）
- **M6.3** PoC canary 实证（需求 2）
- **M6.4** Artifacts 审查链（需求 3）
- **M6.5** 置信度校准（需求 4）
- **M6.6** Vue3 前端全量重写（需求 5/6 的 UI）
