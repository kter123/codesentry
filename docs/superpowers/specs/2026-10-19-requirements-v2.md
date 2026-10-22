# CodeSentry 需求文档 v2.0

> **文档性质**：合并后的需求基线（M0–M5 已交付能力 + 本期新增能力 + brainstorming 扩展）。
> **上游来源**：`agent.md` v1.5、`docs/superpowers/specs/2026-10-19-webui-m5-design.md`、`...-vue3-console-m6-design.md`、`...-m6-sandbox-poc-design.md`、`...-control-plane-design.md`、需求方 2026-10-19 七点新增需求。
> **状态**：待需求方确认。确认后作为本期实现与验收依据；与旧文档冲突处以本文档为准，并在 §12 记录替换关系。

---

## 1. 项目定位与目标

### 1.1 定位

CodeSentry 是基于 **LangGraph** 的 LLM 多智能体源码安全审计平台：对目标仓库自动完成「三引擎静态扫描 → GraphRAG 证据检索 → AI 验证降噪 → 沙箱部署与 PoC 实证 → 人工复核 → 中文审计报告」，并通过 Vue 3 控制台对 Agent、LLM、Prompt、Skills、规则与编排进行全生命周期管理。

- **目标用户**：安全工程师、研发团队、内部安全平台管理员（本地 / 内网部署）。
- **交付形态**：CLI + Web 控制台（Vue 3 + FastAPI）+ CI 集成；单机 Docker Compose 可起。
- **核心差异化**：LangGraph 原生编排（可中断、可回放、可时间旅行）+ 三引擎许可分流 + 证据链与 PoC 实证 + Agent/LLM/Prompt/Skills 全量控制面 + 可复现快照与配置审计。

### 1.2 用户角色

| 角色 | 主要诉求 |
|---|---|
| 安全分析师（analyst） | 发起扫描、审阅 finding、复核 PoC、调整 Prompt/Skill 效果 |
| 平台管理员（admin） | 管理 LLM/Agent/Prompt/Skills/规则/编排、用户与配额、审计与运维 |
| 只读观察者（viewer） | 查看扫描结果、报告、审查链与用量 |
| CI/机器人（token） | 通过 API Token 发起扫描、拉取 SARIF、接收 webhook |

**本期范围确认（2026-10-19）**：单租户 + `admin` / `analyst` / `viewer` 三角色；多租户（FR-42）顺延 P2。

### 1.3 成功标准（可验收）

1. 六种语言（Python、Java、JS/TS、Go、C/C++、PHP）各有样例仓库端到端跑通，产出 SARIF 2.1.0 + Markdown。
2. 每条 finding 附可复核证据：文件行号、调用链、引擎结论、LLM 结论与置信度分解。
3. Triage 后误报显著下降（原始 finding 数下降 ≥ 50%，已确认漏洞零漏报，按 M4 基线回测）。
4. 单仓扫描受硬预算约束（默认 ≤ $10 / ≤ 500k token / ≤ 500 次工具调用），超限熔断并降级出报。
5. 上传 zip 后由 DeployAgent 在 Docker 中完成构建/启动，`deploy_status` 与 `deploy_log` 可查；失败不阻塞报告。
6. 声称可利用（RCE/命令注入等）的 PoC 必须附实证记录（canary/HTTP 回调/文件副作用），否则最高为 `plausible`。
7. 任一 `confirmed` finding 可从报告反向追溯到各 Agent 的输入/输出、模型、Prompt/Skill 版本，并通过哈希链校验。
8. 置信度四分量（raw / evidence / calibrated / verdict-gated）可见；M4 数据集上校准后 ECE ≤ 0.1。
9. Vue 3 控制台全部路由可直接访问、刷新不白屏，API 异常时展示错误态而非空白页。
10. Agent 可绑定 LLM Profile、Prompt 版本与 Skills；LLM/Prompt/Skills/编排均版本化，每次扫描固定快照，可复现、可回放。
11. 用量与成本按 LLM Profile / Agent / 扫描 / 日期可查，配额超限可见告警。

---

## 2. 范围

### 2.1 已交付基线（M0–M5）

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M0 脚手架 | 目录结构、docker-compose、配置加载、CLI 八命令、许可检查脚本 | ✅ |
| M1 引擎集成 | CodeQL（OSS Gate）/ Joern / Semgrep 并行、统一 Finding、SARIF | ✅（php2cpg 降级 Semgrep） |
| M2 数据与 RAG | pgvector 双库、AST 切块、Embedding 双通道、混合检索 | ✅（code/kb 双库） |
| M3 多 Agent 流水线 | LangGraph 六节点、checkpointer、预算、遥测、复核中断、增量审计、PoC 三档 | ✅（LLM 运行时接线有缺口，见 FR-21/FR-23） |
| M3.5 RAG 五库 + GraphRAG | `vuln_cases` / `audit_patterns` / `scan_strategies` / `code_graph` | ⏳ 未开始（遗留项，见 §11） |
| M4 质量评测 | 自建六语言样例 + OWASP Benchmark 抽样 + 真仓降噪 + `bench` 命令 | ✅ |
| M5 WebUI | FastAPI + React 18 + AntD：扫描/图审阅/Agent/Prompt/Skill/规则/复核/设置 | ✅（本期将重写为 Vue 3） |

### 2.2 本期新增（M6）

1. 沙箱部署 Agent（Docker）。
2. PoC 实证验证（拿到执行权限的证明，不保留交互 shell）。
3. PoC 审查链（Agent Artifacts 哈希链 + 反向追溯）。
4. LLM 置信度与校准。
5. Vue 3 + FastAPI 前端全量重写，修复白屏。
6. 控制平面：LLM 管理、Agent 与绑定、Prompt、Skills、用量成本、A/B 与评测、能力矩阵、编排、RBAC、CI、审计回放、健康运维。
7. 平台化扩展：Agent 试跑对比、扫描档位/项目/定时、反馈闭环、知识库运营、AI 辅助、通知集成、数据生命周期、体验与 API/SDK 一致性。
8. **LangGraph 作为运行时内核**：中断/恢复、Send 并行、子图、流式事件、时间旅行、长期记忆。

### 2.3 明确不做（本期）

- SCA 依赖漏洞、容器/IaC 扫描、DAST、自动修复补丁、IDE 插件。
- Skill 内含可执行脚本（仅声明式文本包）。
- 真实交互式反弹 shell / 持久化后门（PoC 仅证明代码执行，不保留 shell）。
- 公有云 SaaS 计费、跨组织 marketplace。
- 移动端适配（控制台以桌面 1280px+ 为主）。

---

## 3. 术语

| 术语 | 含义 |
|---|---|
| AuditState | LangGraph 共享状态 TypedDict，单次扫描的唯一事实源 |
| Checkpointer | LangGraph `PostgresSaver`，持久化每个 super-step，支持恢复与时间旅行 |
| interrupt / resume | LangGraph 原生人工中断与 `Command(resume=...)` 恢复 |
| Send | LangGraph 按 finding 并行 fan-out 的 API |
| Agent Artifact | 节点级输入/输出摘要 + 哈希，构成审查链 |
| LLM Profile | 一套可复用的模型接入配置（base_url、key、fast/deep 模型、价格、能力） |
| Capability Matrix | 每个 Agent 的引擎白名单、网络/Shell/PoC 执行权限、超时与迭代上限 |
| Canary | 一次带随机 nonce 的可观察副作用，用于证明 PoC 确实执行 |
| ECE | Expected Calibration Error，置信度校准误差 |
| 快照（Snapshot） | 扫描开始时固定的 LLM/Prompt/Skill/规则/编排版本集合 |

---

## 4. 总体架构要求

### 4.1 强制技术栈

| 层 | 选型 |
|---|---|
| 运行时 | Python 3.11+，uv，ruff + mypy，pytest |
| 编排 | **LangGraph**（StateGraph、PostgresSaver、interrupt、Send、subgraph、astream） |
| 后端 | FastAPI + Uvicorn，API 前缀 `/api` |
| 数据库 | PostgreSQL 16 + pgvector（业务 schema 与 checkpoint schema 分层） |
| 前端 | Vue 3.5 + TypeScript + Vite + Vue Router + Pinia + Element Plus |
| 图与图表 | AntV G6 v5（调用图/污点链）、Vue Flow（编排编辑器）、ECharts（用量与观测） |
| 沙箱 | Docker SDK（`docker>=7.2`），受限容器 + 独立 bridge 网络 |
| 构建产物 | `src/codesentry/web/static/`，Vite `base: '/ui/'` |

### 4.2 LangGraph 运行时内核（FR-30，P0）

控制平面不得自行实现编排语义，必须落在 LangGraph 原生能力上：

| 能力 | 平台用法 |
|---|---|
| `StateGraph` + `AuditState` | 唯一事实源；编排模板编译为 StateGraph |
| `add_conditional_edges` / `Command` | triage→retrieval 补查、deploy 失败降级、熔断跳转 |
| `interrupt()` + `Command(resume=...)` | 人工复核；复核决策回灌中断点 |
| `PostgresSaver` | 崩溃恢复、断点续跑、审计基线 |
| `get_state_history` / `update_state` | 时间旅行、节点回放、人工修正后继续 |
| `Send` | 按 finding 并行 triage / PoC |
| `RetryPolicy` / `timeout` | 节点级重试与超时 |
| 子图 | 每个 Agent 可注册为子图（含工具循环） |
| `astream(stream_mode=[...])` | WebSocket 实时事件 |
| `PostgresStore` / `BaseStore` | 跨扫描长期记忆（历史 finding、KB、skill 索引） |
| `langgraph.json` + Studio | 开发期可视化调试；CI 快照回归 |
| `InMemorySaver` | 单测不依赖 Postgres |

实现约束：

1. 节点保持 `state -> partial update`；副作用（DB/Docker/HTTP）只在节点内部。
2. 每个节点同时写 `node_runs` 与 `agent_artifacts`，双轨可交叉校验。
3. 人工复核用 `interrupt()`，不用轮询表；`/api/scans/{id}/resume` 即 `Command(resume=decisions)`。
4. 编排模板只允许调整节点启停、边、重试上限，**不允许注入代码**；未知节点拒绝编译。
5. 流式事件统一为 `node.start / node.end / llm.token / message / interrupt / error / done`。
6. 长任务 `durability="async"`；复核与 PoC 执行 `durability="sync"`。

验收：

- 删除除 recon/scan/report 外的任一节点仍可编译并跑通，`node_runs` 标记 skipped。
- 复核中断后重启进程仍可 resume。
- `get_state_history` 可列出每次节点更新，UI 可回到任一 checkpoint。
- 20 条 finding 使用 `Send` 并行的墙钟时间显著低于串行（记录对比）。
- WS 事件序列完整，前端时间线不依赖轮询。

### 4.3 运行时链路

```text
上传(zip/git/diff) → recon → scan → retrieval → triage → deploy → poc_gen
                                                    ↑         │
                                                    └─补查────┘（最多 3 次）
                                                              ↓
                                                    [human_review] → report
```

### 4.4 部署形态

- `docker compose` 起 PostgreSQL/pgvector；应用可裸跑（venv）或容器化。
- 默认监听 **127.0.0.1**；绑定 `0.0.0.0` 时必须启用认证（替换旧 D36）。
- 所有数据落本地/挂载盘；仅 LLM 请求按需携带必要代码片段。

---

## 5. 功能需求

### 5.1 基线需求（M1–M5）

| 编号 | 需求 | 状态 | 备注 |
|---|---|---|---|
| FR-1 | 仓库扫描与画像 | ✅ | 语言/框架/构建识别、扫描计划 |
| FR-2 | 三引擎静态分析 | ✅ | CodeQL/Joern/Semgrep，统一 Finding |
| FR-3 | 许可 Gate | ✅ | 仅声明 OSS 时启用 CodeQL，声明入库 |
| FR-4 | AI 审计流水线 | ✅ | 六 Agent；LLM 运行时接线本期补齐 |
| FR-5 | RAG 检索与 GraphRAG | ✅ 最小闭环 | code/kb + vuln_cases/audit_patterns/scan_strategies + code_graph BFS；仅 Python 图，向量重排待续 |
| FR-6 | 审计报告 | ✅ | Markdown + SARIF 2.1.0 |
| FR-7 | 预算与可观测 | ✅ | budget_ledger、node_runs、checkpoint |
| FR-8 | 规则自管理 | ✅ | 规则集版本化、validate |
| FR-9 | 人工复核 | ✅ | interrupt/resume + WebUI 队列 |
| FR-10 | 增量审计 | ✅ | diff 可达闭包 + CI 退出码 |
| FR-11 | WebUI Agent 管理 | ✅ | React 版；本期 Vue3 重写并扩展 |
| FR-12 | Skill 装载与管理 | ◐ | 上传/分配已交付；运行时可复现注入本期补齐 |
| FR-13 | PoC 生成与验证 | ✅ | 分级 PoC、三档判定、日志 |
| FR-14 | PoC 合规与安全 | ✅ | 默认 off、sandbox 禁出网、危险模式拒绝 |

### 5.2 新增需求

优先级：**P0** = 本期验收必须；**P1** = 本期强烈建议；**P2** = 后续迭代。

#### A. 运行时与可信验证

##### FR-15 沙箱部署 Agent（P0）

1. 图新增 `deploy` 节点：`triage → deploy → poc_gen`。
2. 语言探测复用现有能力；内置配方覆盖 Python（requirements/入口/uvicorn/gunicorn/flask）、PHP（`php -S`）、JS（`npm ci/start`）、Java（Maven 打包后启动）、Go/C（标记 disabled 并落因）。
3. 容器化执行：容器名 `codesentry-target-{scan_id}`，独立 bridge 网络，CPU/内存限额，源码只读挂载，非 root，宿主随机端口仅绑定 127.0.0.1。
4. 健康探测：HTTP 200 → `ready`；超时 → `degraded`；无 Docker/构建失败 → `disabled`；`POC_RUN=off` → 只构建不启动，状态 `built`。
5. `scans.deploy_status / deploy_log / target_url` 落库；失败不阻塞报告，PoC 最高 `plausible`。
6. 扫描结束或删除扫描时清理容器、网络与临时卷；超时与资源限制可配置。
7. 默认禁止出网；确需回连时仅允许显式白名单。
8. **部署配方插件化（本期一步到位，2026-10-19 确认）**：定义 `DeployRecipe` 插件接口（`detect / build / run / health / cleanup`）；内置配方随包提供；用户配方以版本化声明式 YAML + 受限钩子上传，经校验、预览、启用后生效；插件不得在宿主执行任意代码，构建与启动一律在目标容器内；危险步骤（宿主命令、越权挂载、特权模式）拒绝；配方版本随扫描快照固定。

验收：上传含 `requirements.txt + app.py` 的 zip → `deploy_status=ready`（off 时 `built`），`target_url` 非空；删除扫描后无残留容器。

##### FR-16 PoC 实证验证（P0）

1. `verified/confirmed` 必须附实证记录，LLM 自述不算。
2. 三种协议：① 命令回显 `echo CODESENTRY-{nonce}`；② 宿主 `127.0.0.1` 一次性 HTTP listener 回调；③ 容器内文件副作用 `touch /tmp/{nonce}` 后检查。
3. 每个 finding 生成唯一 nonce；`verification_method` 记录协议，`verification_nonce` 记录凭证。
4. **不建立交互式 shell、不保留反弹 shell、不写持久化后门**；危险 payload（`rm -rf`、`sudo`、反弹 shell、管道执行）静态拒绝。
5. 执行仅限本机目标容器/sandbox 内；**暂不支持远程 target**，不接受外部主机地址（2026-10-19 确认）；listener 扫描结束即关闭。
6. 无 target 或网络被禁 → `plausible`；执行失败或策略拒绝 → `rejected`。
7. PoC Studio：查看、复制、下载；允许在显式授权下人工编辑并重跑，每次编辑、授权与执行均留痕（2026-10-19 确认）。

验收：自建 RCE 样例 → `confirmed` 且 `execution_log` 含 nonce 命中；无实证 → `plausible`；危险 payload 被拒绝。

##### FR-17 Agent Artifacts 审查链（P0）

1. 每个节点写 `agent_artifacts`：输入/输出摘要（≤4KB）、SHA-256、模型、tokens、序号。
2. `prev_sha256` 链接上一条 output digest，形成防篡改哈希链。
3. `GET /api/scans/{id}/artifacts` 与 `/artifacts/verify`。
4. UI 以 finding 为中心反向展示 `report ← poc_gen ← deploy ← triage ← retrieval ← scan ← recon`，每节点可展开全文。
5. 展示该节点实际使用的 Prompt 版本、Skills 版本、LLM Profile、耗时与 tokens。
6. 哈希链断裂时显著标红并给出断点。

验收：任一 `confirmed` finding 可展开全链；`verify` 通过；篡改任一摘要后校验失败。

##### FR-18 LLM 置信度与校准（P0）

1. 四层模型：`final = verdict_gated(min(raw, evidence, calibrated))`。
2. `raw` 为 LLM 自报；`evidence` 由证据切片相似度与污点 BFS 实链计算；`calibrated` 为温度缩放逻辑回归；`verdict_gated` 对 confirmed/rejected 做门控。
3. 校准参数存 `calibration_params`，含拟合时间与 ECE；支持重拟合。
4. `findings.confidence_parts` 保存四分量；UI badge tooltip 分解展示。
5. 人工复核结论回流校准与评测数据集。
6. 校准版本随扫描快照固定。

验收：M4 数据集 ECE ≤ 0.1（记录校准前基线）；UI 可展开四分量。

#### B. 控制平面

##### FR-19 Vue 3 控制台（P0 核心页 / P1 全量）

1. Vue 3 + TS + Vite + Router + Pinia + Element Plus；构建到 `static/`，`base='/ui/'`。
2. 所有路由支持直接访问与刷新，**禁止白屏**；API 失败展示错误态/重试，不渲染空白。
3. 页面：登录、总览、扫描列表、扫描详情、复核队列、Agent 列表、Agent 详情、LLM 管理、用量成本、Prompt、Skills、规则、编排、审计、设置、用户与 Token。
4. 扫描详情包含：G6 调用图、源码切片、污点播放、部署状态、findings、审查链、置信度。
5. WS 实时事件；骨架屏、空状态、加载态、错误边界。
6. 角色菜单与 403 页面；深浅色主题与中英文（P2）。

验收：16 条路由直接访问均 200 且无白屏；Playwright 冒烟通过；断网/500 时页面有明确错误提示。

##### FR-20 LLM 管理（P0）

1. Profile CRUD：provider、base_url、fast/deep/embedding 模型、温度、超时、并发。
2. **Provider 预设**：内置 OpenAI 兼容、Anthropic 兼容、Ollama、Azure、OpenCode Go；预设包含 base_url、鉴权方式、必需请求头、模型前缀规范化与配额窗口。详见 `2026-10-20-opencode-go-provider-design.md`。
3. **逐模型协议**：同一 Profile 的 fast/deep 可走不同协议（如 OpenAI `/chat/completions` 与 Anthropic `/messages`）；`model_protocols` 覆盖 Profile 默认协议。
4. **模型目录与探测**：拉取 `/models`，逐模型探测协议、JSON 模式、工具调用、流式、推理字段与可用性；结果存 `model_catalog` / `capabilities`。
5. API Key 加密落库（Fernet，主密钥来自 `CODESENTRY_SECRET_KEY`），读接口仅返回前 8 位 + `…`，写接口空值表示保留。
6. 单租户仅一个默认 Profile；支持 fallback 链；被 Agent 绑定的 Profile 禁止删除（409）。
7. 路由顺序：Agent 绑定 → fallback → 默认 → `.env` 兜底。
8. 韧性：429/5xx/超时指数退避、切 fallback、熔断与半开、并发上限；`MissingSessionID` / `ModelProtocolUnsupported` 归类为配置错误，不盲目重试。
9. **推理模型处理**：解析 `reasoning_content` / `reasoning` / Anthropic `thinking`；推理内容不进报告正文，但 token 计入预算。
10. 密钥轮换与主密钥轮换（重加密）；日志/报告/导出永不含完整密钥。

验收：密钥掩码；默认唯一；429 自动切换；OpenCode Go 预设可连通且能按模型切换协议；推理输出可解析；成本与配额计算正确。

##### FR-21 Agent 管理与绑定（P0）

1. 内置 Agent 注册表 + 自定义 Agent 定义（版本化）。
2. 每 Agent 可配置：启停、显示名、LLM Profile、模型角色（fast/deep）、Prompt 版本、Skills、预算覆写、温度覆写、超时、最大迭代、能力矩阵。
3. 绑定变更下次扫描生效；每次扫描固定快照。
4. `enabled=false` → 节点跳过并记 `skipped`，链路继续。
5. `dry-run`：给定样例 state，渲染最终 system prompt（含 Skills 注入）与 token 估算，不落库、不调外部工具。
6. `preview-prompt`：返回 Prompt 版本、Skills 注入块、token 分解。
7. 观测：调用次数、成功率、P50/P95 耗时、tokens、verdict 分布。
8. Agent Bundle 导入/导出（YAML/JSON，脱敏）（P1）。
9. 修复现有缺口：`run_triage` / `run_poc_gen` / `run_recon` / `run_retrieval` / `run_report` 必须实际使用 `load_prompt` + `skills_for_agent` + 绑定的 LLM，而不是 `llm=None`。

验收：绑定解析顺序正确；disabled 跳过；dry-run 与实际注入一致；扫描快照含 Prompt/Skill/LLM 版本。

##### FR-22 能力矩阵与工具权限（P0）

1. `capabilities`：引擎白名单、`network`、`shell`、`poc_exec`、文件写入、HTTP 客户端、最大 findings。
2. 运行时门禁：`scan` 仅调度白名单引擎；`poc_gen` 无 `poc_exec` 时强制 `plausible`；`network=false` 禁 listener/外连；`shell=false` 禁容器命令执行。
3. 默认值：recon/retrieval/triage/report 全关；scan 开引擎与 shell；poc_gen 仅在 sandbox 授权时开启网络/Shell/PoC 执行。
4. UI 以徽章展示与编辑；变更进审计。
5. 被拒绝的操作记录到 `state.messages` 与节点日志，不崩溃。

验收：`network=false` 时回调被阻断；无 `poc_exec` 时 verdict ≤ plausible；拒绝有记录。

##### FR-23 Prompt 全生命周期（P1）

1. 按 Agent 版本化；同一 Agent 仅一个 `active`；激活、回滚、diff。
2. 编辑支持 Jinja2 变量、输出 JSON Schema 声明、token 估算。
3. Lint：长度上限、必须包含输出结构、危险指令检测、不可信内容分隔符检查。
4. 组合预览：基础人设 + 任务模板 + Skills 注入 + 输出契约，展示 token 分解。
5. A/B：按比例分流，扫描创建时固定版本并写快照；结果按版本聚合。
6. 评测：数据集 `selfbuilt` / `bmj_sample`，真实 LLM 跑 Triage，指标 recall/precision/FP/FN/ECE 存 `prompt_evals`。
7. CI 回归：PR 上跑评测，指标下降超阈值失败（P1）。
8. Prompt 注入防护：仓库内容视为不可信数据，使用明确分隔符与指令层级。

验收：激活唯一；回滚生成新版本；A/B 比例符合；评测指标落库。

##### FR-24 Skills 运营（P1）

1. 上传 SKILL.md 或 zip；frontmatter `name/description` 必填；路径穿越与大小校验。
2. 版本化、内容哈希、回滚、启停。
3. 分配矩阵 Agent × Skill；支持 `version_pin` 与 `priority`；批量分配。
4. 注入预览：每 Agent 注入块与 token 估算；超限按 8K/32K 截断并告警。
5. 使用追踪：哪些扫描/Agent 使用、版本、效果对比。
6. 质量与来源：作者、许可、来源、审核状态、审批流（P1）。
7. 冲突检测（矛盾指令）（P2）。
8. 不允许可执行脚本。

验收：非法 frontmatter 拒绝；版本锁定生效；超限截断；可查使用记录。

##### FR-25 用量与成本（P1）

1. 每次 LLM 调用写 `llm_usage`（profile/agent/model/tokens/cost/latency/ok/error）。
2. 看板按 Profile / Agent / 扫描 / 日期聚合；含 token、费用、延迟、错误率。
3. 月度配额（token/USD），80% 告警，可配置硬停。
4. 扫描前成本预估（按仓库规模与档位）（P1）。
5. 模型评测排行榜：质量/成本/延迟（P1）。
6. 导出 CSV（P2）。

验收：聚合与台账一致；配额告警；预估误差在可接受范围。

##### FR-26 可视化编排（P1）

1. `graph_templates` JSON：nodes/edges/settings；版本化、激活、快照。
2. 校验：必须含 `recon → scan → report`；仅允许 `triage→retrieval` 回边且带上限；节点必须在已知集合内。
3. 编译为 StateGraph；模板不能注入代码；未知节点拒绝。
4. Vue Flow 画布：节点面板、属性面板、连线、保存新版本、设为默认。
5. 编译预检与版本 diff（P1）。
6. 管理员可编辑，analyst 只读。

验收：非法模板被拒绝；禁用节点仍可编译；扫描快照含模板版本。

##### FR-27 身份、角色与 Token（P0 最小集 / P1 多租户）

1. 本地账号 + 角色（admin/analyst/viewer）；密码哈希（argon2/bcrypt）；**本期单租户**（2026-10-19 确认）。
2. JWT（HS256）存 HttpOnly Cookie，TTL 12h；支持登出与过期。
3. API Token `cs_<prefix>_<secret>`，仅创建时返回一次；库中存 SHA-256；scope 到端点；可过期与吊销。
4. 保留默认租户 schema，本期不启用多租户隔离；多租户列为 P2（FR-42）。
5. 所有登录、失败、权限拒绝进审计。
6. SSO/OIDC（P2）。

验收：登录/登出；角色越权 403；Token scope 生效；过期失效。

##### FR-28 CI 与交付（P1）

1. Bearer Token 创建扫描；支持幂等键。
2. `GET /api/scans/{id}/sarif`；`codesentry scan --fail-on high` 返回非零。
3. Webhook：`scan.completed/failed/review.completed`，HMAC-SHA256 签名头，失败重试。
4. GitHub Action / GitLab CI 示例（P1）。
5. PR 内联评论（P2）。

验收：Token 扫描成功；SARIF 有效；签名校验通过；`--fail-on` 退出码正确。

##### FR-29 审计、快照与回放（P1）

1. 配置写操作统一写 `config_audit`（actor/action/target/before/after），密钥脱敏。
2. 扫描快照：LLM Profile、Prompt、Skills、规则集、编排模板、引擎版本。
3. 整扫描重放：复用源码 + 固定快照创建新扫描（`mode=replay`）。
4. 节点重放：用 `agent_artifacts.input_preview` 构造 state，只跑该节点并展示 diff。
5. LangGraph 时间旅行：`get_state_history` + `update_state`（P1）。
6. 审计导出（P2）。

验收：每次配置写有审计；导出不含密钥；replay 使用快照而非当前配置。

##### FR-31 健康与运维（P1）

1. `GET /api/health`：DB、LLM Profiles、Embedding、Docker、引擎版本、队列。
2. Docker 清理：残留 `codesentry-target-*` 容器与未引用镜像，仅 admin + 二次确认。
3. 磁盘占用与可清理项。
4. Prometheus 指标（P2）。
5. 备份/恢复指引；配置导出导入（脱敏）。

验收：健康状态反映真实故障；清理仅 admin；无孤儿容器。

#### C. 平台化扩展

##### FR-32 Agent 试跑与对比工作台（P1）

1. Fixture 库：样例代码切片/ finding / evidence。
2. 单 Agent 试跑：mock 工具或授权真实工具，输出、tokens、成本、耗时。
3. 双配置对比：同一输入，两个 Prompt/Skill/LLM 配置并排 diff。
4. 一键将胜出配置设为激活版本（需确认）。
5. 试跑不写生产 findings，可留存为测试记录。

验收：试跑可复现；对比展示差异；激活需显式确认。

##### FR-33 项目、扫描档位与调度（P1）

1. 项目（project）聚合仓库与历史扫描、基线。
2. 扫描档位：quick / standard / deep（节点启停、模型角色、预算、引擎组合）。
3. 并发与优先级队列；取消、暂停、恢复。
4. 定时扫描（cron）与批量扫描。
5. 增量扫描与基线对比。

验收：档位生效；并发受限；取消在 5s 内生效；定时任务可停用。

##### FR-34 反馈闭环与知识沉淀（P1）

1. 人工复核结论回流：校准参数、评测数据集、规则命中反馈。
2. `confirmed` finding 一键沉淀为 `vuln_cases`（含利用链、PoC、修复）。
3. 误报样本沉淀为负例，用于 Prompt/Skill 评测。
4. 指标趋势：误报率、确认率、成本随版本变化。

验收：复核后数据进入对应数据集；案例可在后续扫描被检索；趋势可查。

##### FR-35 知识库运营（P2）

1. 目录/zip 导入、切块预览、embedding 与索引状态。
2. 重建索引、删除、按租户隔离。
3. 检索测试与命中解释。
4. 与 `vuln_cases` / `audit_patterns` / `scan_strategies` 分库管理。

验收：导入幂等；重建可观测；检索可复现。

##### FR-36 AI 辅助运营（P2）

1. Ask CodeSentry：基于扫描 artifacts 与知识库的 RAG 问答，答案带引用。
2. Copilot：根据评测失败样本建议 Prompt/Skill 修改，人工确认后才应用。
3. 复核队列排序：calibrated confidence × severity × 影响面。
4. 禁止跨租户/跨扫描越权检索；所有回答标注来源。

验收：引用可点开；建议不自动生效；越权请求被拒绝。

##### FR-37 安全加固与不可信输入防护（P0）

1. 仓库内容一律视为不可信数据：明确分隔符、指令层级、禁止执行代码中的指令。
2. 发送 LLM 前做密钥/凭证脱敏；上传仓库做 secret 扫描与提示。
3. git URL 仅 https；阻断私网/回环地址（SSRF 防护）；webhook 目标同样校验；不提供远程 PoC target。
4. Cookie 认证启用 CSRF 防护；安全 Cookie；登录限流。
5. 沙箱：非 root、只读根文件系统（可行时）、能力最小化、默认禁出网、独立网络。
6. 上传 zip 防穿越、500MB 上限；切片接口路径白名单。
7. 依赖许可检查进 CI；发行物不含第三方受限规则/二进制。

验收：注入样例无法覆盖系统指令；密钥不出现在日志；SSRF 被阻断；沙箱逃逸用例失败。

##### FR-38 通知与代码平台集成（P2）

1. 事件订阅：扫描完成/失败、复核完成、配额告警、健康异常。
2. 渠道：Webhook、邮件、Slack/飞书（择一优先）。
3. PR 评论回写（GitHub/GitLab）。
4. 重试与死信记录。

验收：事件触发一次且签名正确；失败可重试；可关闭。

##### FR-39 数据生命周期与隐私（P2）

1. 保留策略：扫描、artifacts、日志、报告可配置过期。
2. 删除级联：DB 行、work 目录、容器、缓存。
3. 数据导出与脱敏。
4. 密钥/凭证/个人信息脱敏规则。

验收：过期清理可审计；删除无残留；导出不含敏感信息。

##### FR-40 控制台体验（P1）

1. 首次启动向导：管理员、LLM、Embedding、数据库检查。
2. 全局搜索与命令面板；常用快捷键。
3. 骨架屏、空状态、错误边界、重试。
4. 深色模式与中英文（P2）。
5. 可访问性：键盘可达、对比度、焦点管理。

验收：首次启动可完成配置；断网不白屏；关键操作键盘可达。

##### FR-41 API/SDK/CLI 一致性（P2）

1. OpenAPI 3.1 文档完整；生成 TypeScript 客户端。
2. CLI 与 API 能力对齐；新增 `serve`、`user`、`config`、`eval`、`replay` 子命令。
3. 幂等键、分页、错误码规范、版本与弃用策略。

验收：OpenAPI 无缺漏；CLI 与 API 行为一致；错误码稳定。

##### FR-42 多租户与配额（P2）

1. 租户隔离：扫描、配置、知识库、用量、审计。
2. 租户配额：并发扫描、月度 token/USD、存储。
3. 功能开关按租户配置。
4. 管理员跨租户视图。

验收：A 租户不可见 B 租户数据；配额生效；开关按租户生效。

##### FR-43 规则运营增强（P1）

1. 规则集版本化、激活、回滚、validate、单规则试跑。
2. 命中统计与误报反馈。
3. 高噪声规则建议（需人工确认后停用）。
4. 语言/框架映射与规则集模板。

验收：版本可回滚；命中统计准确；建议不自动生效。

##### FR-44 审查协作（P2）

1. Finding 评论与线程、@提醒。
2. 复核任务指派与 SLA。
3. 批量决策与复核历史。
4. 决策理由结构化（误报原因分类）。

验收：评论持久化；指派可见；批量决策留痕。

---

## 6. 非功能需求

| 编号 | 需求 |
|---|---|
| NFR-1 | 语言支持：Python、Java、JS/TS、Go、C/C++、PHP；弱组合显式降级并标注 |
| NFR-2 | 可复现：同仓库同配置路由可复现（温度 0）；快照含 LLM Profile、Prompt、Skills、规则、编排模板、引擎版本 |
| NFR-3 | 数据本地化：代码、向量、结果存本地 PostgreSQL/挂载盘；仅必要片段出网 |
| NFR-4 | 部署：`docker compose` 一键起库；应用可裸跑或容器化；Joern 需 JDK 17+ |
| NFR-5 | 许可合规：依赖逐项记录 license；发行物不含受限组件 |
| NFR-6 | 性能：上传 ≤500MB；WS 事件端到端 <1s；20 条 finding Send 并行加速 ≥2×；本地页面首屏 <2s；取消扫描 <5s |
| NFR-7 | 安全：OWASP Top 10 防护；密钥加密与掩码；RBAC；审计；沙箱隔离 |
| NFR-8 | 可观测：node_runs、llm_usage、artifacts、audit；错误分类与追踪 ID |
| NFR-9 | 可用性：进程重启可恢复；单引擎/单 LLM 失败可降级；失败不阻塞报告 |
| NFR-10 | 兼容性：API 前缀 `/api`；前端 `base='/ui/'`；支持 Chrome/Edge/Safari 最近两个大版本 |
| NFR-11 | 可测试：单测不依赖外网（InMemorySaver + mock LLM）；集成测试用真实 DB；E2E 覆盖关键链路 |
| NFR-12 | 可扩展：新增 Agent/引擎/LLM Provider 通过注册表接入，不修改编排主流程 |
| NFR-13 | 可维护：模块边界清晰，单文件职责单一；新增代码遵循现有模式 |

---

## 7. 数据需求

### 7.1 已有核心表

`scans`、`findings`、`code_chunks`、`kb_chunks`、`budget_ledger`、`node_runs`、`agent_configs`、`prompt_versions`、`skills`/`skill_versions`/`skill_assignments`、`rule_sets`、`app_settings`、LangGraph checkpoint 表。

### 7.2 本期新增表

| 表 | 用途 |
|---|---|
| `llm_profiles` | LLM 接入配置、加密密钥、价格、能力、fallback、默认标记 |
| `llm_usage` | 每次 LLM 调用的用量与成本 |
| `config_audit` | 配置变更 before/after 审计 |
| `graph_templates` | 可视化编排模板与版本 |
| `agent_artifacts` | 审查链节点输入/输出与哈希链 |
| `calibration_params` | 置信度校准参数与 ECE |
| `prompt_evals` | Prompt 评测指标 |
| `tenants` / `users` / `api_tokens` | 身份、角色、CI Token |
| `webhooks` | 事件订阅与签名密钥 |
| `projects` / `scan_schedules` | 项目聚合与定时扫描（P1） |
| `review_comments` | 审查评论与协作（P2） |
| `notifications` | 通知投递与死信（P2） |
| `agent_definitions` | 自定义 Agent 版本（P1） |
| `deploy_recipes` | 部署配方插件：语言、版本、步骤 DSL、校验状态、启用标记 |

### 7.3 字段扩展

- `scans`：`deploy_status`、`deploy_log`、`target_url`、`llm_profile_id`、`graph_snapshot`、`error_reason`、`rule_set_version`。
- `findings`：`verification_method`、`verification_nonce`、`confidence_parts`、`review_reason`。
- `agent_configs`：`llm_profile_id`、`display_name`、`capabilities`、`timeout_s`、`max_iterations`、`temperature_override`、`updated_at`。
- `prompt_versions`：`body_sha256`、`tenant_id`、`active` 唯一约束。
- `skill_assignments`：`version_pin`、`priority`、`tenant_id`。
- `rule_sets`：`tenant_id`、`active`。
- `llm_profiles`：`protocol`、`extra_headers`、`quota_windows`、`model_catalog`、`model_protocols`、`billing_mode`。

所有新增列使用 `ADD COLUMN IF NOT EXISTS`，支持幂等迁移。

---

## 8. 接口需求

### 8.1 HTTP API（前缀 `/api`）

| 分组 | 端点示例 |
|---|---|
| 认证 | `POST /auth/login`、`POST /auth/logout`、`GET /auth/me` |
| 扫描 | `POST /scans`、`GET /scans`、`GET /scans/{id}`、`DELETE /scans/{id}`、`POST /scans/{id}/resume`、`POST /scans/{id}/replay`、`GET /scans/{id}/sarif`、`GET /scans/compare` |
| 图与证据 | `GET /scans/{id}/graph`、`GET /findings/{id}`、`GET /scans/{id}/source`、`GET /scans/{id}/artifacts`、`GET /scans/{id}/artifacts/verify` |
| Agent | `GET/PUT /agents/{name}`、`GET /agents/{name}/stats`、`POST /agents/{name}/dry-run`、`POST /agents/{name}/preview-prompt` |
| LLM | `GET/POST/PUT/DELETE /llm-profiles`、`POST /llm-profiles/{id}/test`、`POST /llm-profiles/{id}/probe` |
| 用量 | `GET /usage/summary`、`GET /usage/quota` |
| Prompt | `GET/POST /prompts`、`/prompts/{name}/versions`、`/prompts/{name}/activate`、`/prompts/{name}/rollback`、`POST /prompts/eval`、`GET /prompt-evals` |
| Skills | `GET/POST /skills`、`POST /skills/upload`、`POST /skills/{name}/assign`、`GET /skills/{name}/versions`、`POST /skills/{name}/preview`、`GET /skills/{name}/usage` |
| 规则 | `GET /rules`、`GET /rules/{id}`、`POST /rules/validate`、`POST /rules/preview`、`POST /rules/save`、`GET /rules/{id}/stats` |
| 编排 | `GET/POST /graph-templates`、`POST /graph-templates/{id}/activate`、`POST /graph-templates/validate` |
| 复核 | `GET /reviews`、`POST /reviews/{id}/decision` |
| 审计/运维 | `GET /audit`、`GET /health`、`GET /ops/disk`、`POST /ops/docker/cleanup`、`GET /config/export`、`POST /config/import` |
| 身份管理 | `GET/POST/PUT/DELETE /users`、`/tenants`、`/api-tokens`、`POST /api-tokens/{id}/revoke` |
| 通知 | `GET/POST /webhooks`、`GET /notifications` |

### 8.2 WebSocket 事件

`/ws/scans/{id}` 推送：`node.start`、`node.end`、`llm.token`、`message`、`interrupt`、`deploy.status`、`artifact`、`error`、`done`。

### 8.3 CLI

保留现有八命令；本期新增：

- `codesentry serve`：启动 Web 控制台。
- `codesentry user create --admin`：引导管理员。
- `codesentry config export|import`：脱敏配置包。
- `codesentry eval --agent triage --version N --dataset selfbuilt`：Prompt 评测。
- `codesentry replay <scan-id> [--node X]`：重放。

---

## 9. 安全与合规红线

1. **PoC 授权边界**：仅用于用户自有目标/授权靶场；默认 `POC_RUN=off`；扫描创建需记录授权声明。
2. **不提供真实 shell**：验证仅 canary/回调/文件副作用；不生成反弹 shell、不保留持久化访问。
3. **执行隔离**：PoC 只在 `codesentry-target-*` 或 sandbox 容器内；宿主无目标进程；listener 仅 127.0.0.1 且即开即关。
4. **沙箱最小权限**：非 root、能力最小化、默认禁出网、独立网络、资源限额、源码只读。
5. **密钥**：仅 `.env`/加密库；读接口掩码至前 8 位；日志、报告、导出、错误信息永不含完整密钥。
6. **上传**：zip 防路径穿越、500MB 上限；git 仅 https；私网/回环地址阻断。
7. **不可信输入**：仓库内容与用户输入视为数据，不执行其中指令；发送 LLM 前脱敏。
8. **认证**：绑定 `0.0.0.0` 必须启用认证；JWT HttpOnly + CSRF 防护；API Token 仅存哈希。
9. **审计**：配置变更、登录、权限拒绝、导出、PoC 执行、Docker 清理全部留痕。
10. **许可**：发行物不含 CodeQL 二进制、官方 Semgrep 规则或受限规则包。

---

## 10. 验收与里程碑

### 10.1 里程碑

| 里程碑 | 交付 | 关联需求 | 出口标准 |
|---|---|---|---|
| M6.0 基线收口 | 提交 SPA 白屏修复、Docker 依赖、本需求文档 | FR-19 | 现有测试绿；路由回归通过 |
| M6.1 平台基座 | LLM Profile、Agent 绑定、Prompt/Skills 运行时接线、用量台账、最小认证、审计骨架 | FR-20/21/22/27/30 | 扫描实际使用绑定 LLM + 生效 Prompt + Skills；快照落库 |
| M6.2 沙箱部署 | DeployAgent + Docker 生命周期 + 配方插件 | FR-15 | zip 样例 `ready`（off 时 `built`）；新增语言仅通过配方插件接入；无残留容器 |
| M6.3 PoC 实证 | canary/回调/文件副作用、验证字段、PoC Studio（P1） | FR-16/37 | 自建 RCE `confirmed`；危险 payload 拒绝 |
| M6.4 审查链与置信度 | artifacts 哈希链、反向追溯 UI、校准四层、反馈闭环 | FR-17/18/34 | 全链可追溯且校验通过；ECE ≤ 0.1 |
| M6.5 Vue3 控制台 | 核心 9 页 + 深链无白屏 | FR-19 | 路由 200、无白屏、Playwright 冒烟 |
| M6.6 控制面增强 | Prompt A/B + 评测、Skills 运营、编排、规则、CI | FR-23/24/26/28/43 | 各闭环可演示；快照与回滚生效 |
| M6.7 平台化增强 | 用量看板、健康运维、知识库、AI 辅助、通知、体验、配额 | FR-25/31/32/33/35/36/38/40/42/44 | 关键页面可用；配额与通知生效 |
| M6.8 验收与加固 | 全量测试、安全测试、性能压测、文档 | 全部 | 测试全绿；红线检查通过 |

**实现进展（2026-10-22）**：M6.0 与 M6.1 后端基座已完成。M6.2 沙箱部署已真实验证（scan 612/637 `ready`、127.0.0.1 端口、target 200、清理）；M6.3 PoC canary 已真实验证（scan 613 命令回显命中 nonce）；M6.4 Artifacts/tool_trace/置信度已完成；M6.5 Vue 3 控制台（审查链 tab、实时 Agent 事件）已完成；M6.6 编排/评测/webhook/工具循环部分完成；M3.5 RAG 五库 + GraphRAG 最小闭环已完成（经验检索进入 Triage/PoC/Recon，复核沉淀案例；仅 Python 图/无向量重排）。多租户、AI 辅助、知识库运营、数据生命周期、SDK、审查协作待续。

### 10.2 需求追踪
| 需求组 | 设计规格 | 里程碑 |
|---|---|---|
| FR-15 | `2026-10-19-m6-sandbox-poc-design.md` §一、`...-vue3-console-m6-design.md` §8 | M6.2 |
| FR-16 | `...-m6-sandbox-poc-design.md` §二、`...-vue3-console-m6-design.md` §9 | M6.3 |
| FR-17 | `...-m6-sandbox-poc-design.md` §三、`...-vue3-console-m6-design.md` §10 | M6.4 |
| FR-18 | `...-m6-sandbox-poc-design.md` §四、`...-vue3-console-m6-design.md` §11 | M6.4 |
| FR-19 | `2026-10-19-vue3-console-m6-design.md` §2/§12 | M6.5 |
| FR-20 | `2026-10-19-control-plane-design.md` §3、`2026-10-20-opencode-go-provider-design.md` | M6.1 |
| FR-21–29, 31 | `2026-10-19-control-plane-design.md` §2–§11 | M6.1/M6.6/M6.7 |
| FR-30 | `2026-10-19-control-plane-design.md` §1.5 | M6.1 |
| FR-32–44 | 本文档 §5.2 | M6.6/M6.7 |

### 10.3 回归与测试要求

- 后端单测：LLM 路由与掩码、Agent 绑定、能力门禁、Prompt 激活/回滚、Skills 截断、artifacts 哈希链、置信度、认证与 RBAC、编排校验、审计脱敏。
- 集成测试：真实 PostgreSQL（pgvector）、真实容器（可用时）、Mock LLM 回放。
- E2E：上传 → 扫描 → 部署 → PoC → 复核 → 报告 → 审查链全链路。
- 前端：`npm run build` 通过；Playwright 覆盖 16 路由与关键表单。
- 安全：提示注入样例、SSRF、路径穿越、权限越权、密钥泄露扫描。

---

## 11. 风险与待决问题

### 11.1 风险

| 风险 | 缓解 |
|---|---|
| 部署配方脆弱（Java 构建、JS 原生依赖） | 超时降级 `disabled` 并落因；配方可配置；失败不阻塞报告 |
| canary 只能证明代码执行路径，不等于完整利用 | verdict 语义明确为「实证执行」；报告注明验证范围 |
| LLM 成本失控 | 预算熔断 + Profile 路由 + 配额 + 降级 fast 模型 |
| Prompt 注入来自仓库内容 | 分隔符 + 指令层级 + 注入测试 + 脱敏 |
| 多租户与 RBAC 拉大范围 | P0 仅单租户最小 RBAC；多租户列 P1/P2 |
| Vue 重写引入回归 | API 契约不变；路由与契约测试先行；灰度对比 |
| 校准数据不足导致 ECE 不稳定 | 以人工复核持续积累；记录样本量与置信区间 |
| 编排自由度过高导致不可控 | 白名单节点 + 受限边 + 编译预检 |
| artifacts 预览截断丢失证据 | 预览 ≤4KB，完整内容落 work 目录并以哈希引用 |

### 11.2 已确认决策（2026-10-19）

1. **认证范围**：单租户 + `admin` / `analyst` / `viewer` 三角色；完整多租户顺延 P2。
2. **PoC 人工编辑**：允许在显式授权下编辑并重跑，编辑、授权、执行全部留痕。
3. **远程 target**：暂不支持，仅限本机 sandbox / 目标容器。
4. **部署配方**：本期一步到位插件化，`DeployRecipe` 接口 + 版本化配方包。
5. **M3.5 与 M6 的关系**：拆分并行，避免整体阻塞：
   - **M3.5a（与 M6.1/M6.2 同期）**：`code_graph` 抽边入库 + 递归 CTE / BFS API，供 FR-17 审查链与 FR-18 证据分使用；
   - **M3.5b（与 M6.4/M6.7 同期）**：`vuln_cases` / `audit_patterns` / `scan_strategies` 三库与反馈闭环（FR-34/35）合并实施。

### 11.3 仍待确认

1. 校准与评测数据集的标注人力与来源。
2. 通知渠道优先级（Webhook / 邮件 / Slack / 飞书）。
3. 推理型模型的 `reasoning` 内容是否需要在审查链 UI 中可见（建议可见但默认折叠，且不进入报告）。

---

## 12. 变更记录（相对 `agent.md` v1.5）

| 项 | 旧结论 | v2.0 结论 |
|---|---|---|
| D16 WebUI 技术栈 | React + Ant Design | **Vue 3 + Element Plus**（FastAPI 不变） |
| D19 Agent 管理深度 | 监控 + 模型/预算 + Prompt | 扩展为 LLM/Prompt/Skills/能力矩阵/试跑/观测/审计全量控制面 |
| D36 默认监听 | 默认 0.0.0.0，无认证风险自担 | **默认 127.0.0.1；绑定 0.0.0.0 必须启用认证** |
| 认证范围 | v2 候选 | **单租户 + 三角色**（2026-10-19 确认）；多租户 P2 |
| PoC 验证 | 三档判定，执行日志 | 增加 canary/回调/文件副作用实证；禁止真实 shell |
| 可复现要素 | Prompt + Skill + Agent 配置 | 增加 LLM Profile、规则集、编排模板、校准版本 |
| 范围外 | Skill 可执行脚本、多用户认证 | Skill 脚本仍不做；认证提入本期最小集 |
| 部署配方 | 内置配方，插件化留待 v2 | **本期一步到位插件化**（`DeployRecipe` 接口） |
| PoC target | 本地 sandbox 或用户指定环境 | **仅本机容器，暂不支持远程 target** |
| 遗留 | M3.5 未开始 | 拆分为 M3.5a / M3.5b，与 M6 并行（§11.2-5） |

---

*本文档为需求基线，不替代各模块设计规格的实现细节。规格与本文档冲突时，以本文档的需求意图为准，并同步修订规格。*
