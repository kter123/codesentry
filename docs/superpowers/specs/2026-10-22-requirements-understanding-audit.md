# 需求理解与偏差审计（2026-10-22）

> 目的：把 M0–M6 的全部需求、你的最新设计意图、当前实现状态放在一张图上，明确“已做/部分做/没做/理解可能偏差”的地方。本文档只做审计，不改变代码。

## 1. 需求来源与优先级

发生冲突时，以更新、更具体的需求为准：

1. 你 2026-10-19/20/21 的口头设计澄清（最新意图）
2. `docs/superpowers/specs/2026-10-19-requirements-v2.md`（M6 需求基线，FR-15–FR-44）
3. `agent.md` v1.5（M0–M5 基线，FR-1–FR-14、NFR-1–5）
4. 各模块设计规格（M6 沙箱/PoC、Vue3 控制台、控制平面、OpenCode Go Provider）

## 2. 你的核心设计意图（我的理解）

1. **LangGraph 是运行时内核**：不是“用了 LangGraph 的脚本”，而是 StateGraph、共享 `AuditState`、条件边、interrupt/resume、PostgresSaver、Send、子图、流式事件、时间旅行都要成为平台能力。
2. **多 Agent 协同分析是最重要的产品价值**：要能看见每个 Agent 在做什么、读了什么代码、调了什么工具、得出什么结论、用了哪个 Prompt/Skill/LLM。
3. **PoC 验证是可信度的核心**：声称能拿 shell/执行命令，必须有 canary 证据；不能只靠 LLM 自述或“容器能执行命令”冒充 `verified`。
4. **RAG 是 Agent 的“经验层”**：不是装饰，而是把历史漏洞案例、漏洞模式、项目扫描策略、代码调用图喂给 Triage/PoC，让分析越用越准。
5. **上传 Web 代码包 → 在 Docker 中部署**：CodeSentry 服务本身跑在本地；上传的 Web 项目应被实际构建/启动在 Docker 里，供 Agent 验证；PoC 执行受授权与安全边界约束。
6. **Vue3 + FastAPI 控制台**：所有页面可用、不白屏；LLM Profile、Prompt、Agent 绑定、Skills 可配置；关键过程可见。
7. **项目要能真正跑起来**：本地服务、数据库、LLM Profile、Prompt 配置、上传扫描、报告、复核形成闭环。

## 3. 已交付基线（M0–M5）

| 需求 | 状态 | 说明 |
|---|---|---|
| M0 脚手架 | ✅ | CLI、配置、compose、DDL、许可检查 |
| M1 三引擎 | ✅ | CodeQL（OSS Gate）/Joern/Semgrep，SARIF/MD |
| M2 数据与 RAG | ◐ | code_chunks + kb_chunks + 混合检索；五库其余未做 |
| M3 多 Agent 流水线 | ✅ | 六节点、checkpointer、预算、遥测、复核、增量、PoC 三档 |
| M3.5 五库 + GraphRAG | ❌ | `vuln_cases`/`audit_patterns`/`scan_strategies`/`code_graph` 未实现 |
| M4 质量评测 | ✅ | 自建六语言 + BMJ 抽样 + 真仓降噪 |
| M5 WebUI（React） | ✅ | 已被 Vue3 控制台替代 |

基线 FR-1–FR-14：FR-5 仅完成 code/kb 双库；FR-12 的运行时注入已在 M6.1 补齐；其余完成。

## 4. M6 需求逐项状态

| 编号 | 需求 | 状态 | 证据/缺口 |
|---|---|---|---|
| FR-15 | 沙箱部署 Agent（Docker） | ◐ | 有 DockerDeployer/配方/健康探测/清理；**仅通用镜像 + internal 网络 + `POC_RUN=off` 时只 built**；忽略项目 Dockerfile/compose；真实 ready 未跑通 |
| FR-16 | PoC 实证（canary） | ◐ | 已改为 PoC 自身声明 `{CANARY_CMD}/{CANARY_FILE}/{CANARY_URL}`；mock 测试；真实容器未验证；listener 在 internal 网络不可达 |
| FR-17 | Artifacts 审查链 | ◐ | 哈希链/校验 API/UI tab；真实扫描 594 曾验证 7 节点链；新 DB 已清空 |
| FR-18 | LLM 置信度 | ◐ | 四层模型/校准 API/`confidence_parts`/`tool_trace` 落库；UI 分解展示已加；ECE 数据未重新拟合 |
| FR-19 | Vue3 控制台 | ✅ | 17 视图、16 路由、构建通过；深链 `/ui/*` 可用；白屏回归测试 |
| FR-20 | LLM 管理 | ✅ | 多 Profile、加密/掩码、默认/fallback、OpenCode Go 预设、测试/探测 |
| FR-21 | Agent 管理/绑定 | ◐ | 六内置 Agent、LLM/Prompt/Skills 绑定、dry-run、统计；自定义 Agent/Bundle 未做 |
| FR-22 | 能力矩阵 | ◐ | engines/network/shell/poc_exec；`max_iterations` 工具循环、`budget_override` 已实现；尚未真实 LLM/UI 端到端验证 |
| FR-23 | Prompt 生命周期 | ◐ | 版本/激活/回滚/diff/lint；A/B `ab_json` 与快照分流部分实现；**批量自动评测 runner 未做**；UI 无 A/B 控件 |
| FR-24 | Skills 运营 | ✅ | 上传/版本/分配/版本锁定/优先级/注入预览/使用追踪 |
| FR-25 | 用量与成本 | ✅ | `llm_usage`、聚合、配额、UI |
| FR-26 | 可视化编排 | ◐ | `graph_templates` 后端 CRUD/校验/激活；前端仍是本地 JSON 草稿，未接服务端保存 |
| FR-27 | 身份/RBAC | ✅ | 单租户 + admin/analyst/viewer、JWT、API Token、WS 鉴权 |
| FR-28 | CI/交付 | ◐ | SARIF 下载、replay、webhook；GitHub Action/PR 评论未做 |
| FR-29 | 审计/快照/回放 | ◐ | config_audit、扫描快照、replay API；节点级 replay 未完成 |
| FR-30 | LangGraph 内核 | ◐ | StateGraph/条件边/interrupt/checkpointer/Send/artifacts/节点事件；token 级流式未做 |
| FR-31 | 健康与运维 | ✅ | DB/Profile/Docker/引擎/队列 |
| FR-32 | Agent 试跑/对比 | ❌ | 未实现 |
| FR-33 | 项目/档位/定时 | ❌ | 未实现 |
| FR-34 | 反馈闭环/案例沉淀 | ❌ | 未实现（依赖五库） |
| FR-35 | 知识库运营 | ❌ | 未实现 |
| FR-36 | AI 辅助 | ❌ | Ask CodeSentry/Copilot 未实现 |
| FR-37 | 安全加固 | ◐ | 路径穿越/SSRF/上传/密钥/权限加固；提示注入自动化测试、数据脱敏未完整 |
| FR-38 | 通知 | ◐ | Webhook + HMAC + 事件 + 重试；邮件/Slack/飞书按你要求排除 |
| FR-39 | 数据生命周期 | ❌ | 保留策略/级联删除/导出未实现 |
| FR-40 | 控制台体验 | ◐ | 骨架/空态/错误态；暗色/国际化未做 |
| FR-41 | API/SDK/CLI | ◐ | OpenAPI、CLI 模块入口；TS/Python SDK 未做 |
| FR-42 | 多租户/配额 | ❌ | 单租户；tenant 隔离/配额未做 |
| FR-43 | 规则运营 | ◐ | 列表/校验/保存；命中统计/噪声治理未做 |
| FR-44 | 审查协作 | ❌ | 评论/指派/SLA/批量决策未做 |

## 5. 当前实现与你的意图：主要偏差

### 偏差 A（最重要）：Docker 部署语义

**你的意图（我理解）**：上传 Web 代码包后，应把该 Web 项目实际构建/启动在 Docker 中，形成可验证目标；CodeSentry 本身在本地运行。

**当前实现**：
- 用通用语言镜像（python/php/node）挂载源码启动，**不使用项目自己的 Dockerfile / docker-compose.yml**。
- 默认 `POC_RUN=off` → 只返回 `deploy_status=built`，**不启动容器**。
- 使用 `internal=True` Docker 网络 → **不发布宿主端口**；`target_url` 仅在容器内可达，浏览器打不开。
- 源码只读挂载，JS 构建/写入型项目可能失败。
- 未处理嵌套 zip 根目录、端口探测、环境变量、多服务 compose。
- 扫描结束不自动清理容器（仅删除扫描时清理）。

**结论**：这不是你想要的“上传 Web 包 → Docker 部署 → 可见/可验证”的完整体验，存在明显偏差。

**建议修正**：
1. 部署与 PoC 执行解耦：新增 `DEPLOY_ENABLED`，默认 true；`POC_RUN` 只控制是否执行 PoC。
2. 构建优先级：项目 `Dockerfile` → `docker-compose.yml`（v1 限制单服务）→ 语言配方。
3. 两种网络模式：`host`（仅 127.0.0.1 随机端口，UI 可打开）与 `internal`（严格沙箱，PoC 在容器内）；默认 `host` 更符合本地使用。
4. 可写构建目录、端口探测、env 注入、完整 build/run 日志。
5. 扫描结束/删除/超时自动清理容器与网络。

### 偏差 B：RAG 经验层缺失

**你的意图**：RAG 让 Triage/PoC 复用历史案例、漏洞模式、项目策略，提高分析效率与能力。
**当前**：只有 code/kb 双库；`vuln_cases`、`audit_patterns`、`scan_strategies`、`code_graph` 均未实现；检索结果没有进入 Triage/PoC 的稳定上下文，也没有人工复核后的案例沉淀。
**结论**：这是与“能力提升”目标最大的落差。M3.5 必须补，且优先级应高于 A/B、多租户。

### 偏差 C：多 Agent 过程可见性仍需真实验证

**当前**：artifacts API/UI、tool_trace、WS `node.start/node.end` 已加；真实扫描曾验证 7 节点链。
**缺口**：新 DB 清空后未重新跑；没有 token 级流式；工具循环尚未在真实 LLM 长链上验证；UI 审查链/工具轨迹是新加的，未做浏览器端验收。

### 偏差 D：PoC 实证的真实性

**当前**：canary 逻辑正确（PoC 必须自己声明占位符）；mock 测试通过。
**缺口**：internal 网络下 HTTP listener 回调不可达；真实 Docker/canary 未成功跑通；命令回显/文件副作用需在真实容器验证。

### 偏差 E：Prompt A/B 与自动评测

**当前**：`ab_json` schema/分流/快照部分完成；评测结果记录 API 有。
**缺口**：没有真正的批量评测 runner；A/B 未在 UI 暴露；分流在 Web 上传路径的 scan_id 绑定未完整接线。

### 偏差 F：not done 的 P2

多租户、AI 辅助、知识库运营、反馈闭环、数据生命周期、SDK、审查协作、Agent 试跑/对比、项目/定时扫描均未实现。

## 6. 建议的执行顺序（按你的设计）

1. **修正 Docker 部署语义**（偏差 A）→ 上传 Web 包能真正构建/启动/访问，并自动清理。
2. **RAG 经验层**（偏差 B）→ `code_graph` + `vuln_cases` 先接入 Triage/PoC，再做 feedback。
3. **Agent 可见性真实验收**（偏差 C）→ 用真实 LLM 跑一条完整扫描，浏览器看审查链/工具轨迹/实时事件。
4. **PoC 真实联调**（偏差 D）→ 至少 canary 命令/文件副作用在真实容器成立。
5. Prompt A/B 自动评测（偏差 E）。
6. 多租户、AI 辅助、KB 运营、审查协作、SDK、数据生命周期。

## 7. 需要你确认的两个关键选择

1. **部署默认行为**：上传后默认就启动容器（推荐），还是仍由 `POC_RUN`/显式开关控制？
2. **目标可达性**：默认 `host` 模式（127.0.0.1 随机端口，浏览器可打开，推荐本地使用），还是默认 `internal`（更安全，只能在容器内验证）？

这两个选择会决定 FR-15/FR-16 的实现方向；确认后我再改代码，避免继续在错误语义上加功能。
