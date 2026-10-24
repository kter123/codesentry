# CodeSentry 核心需求总览（2026-10-24 重梳理）

> 合并来源：`agent.md` v1.5、`docs/superpowers/specs/2026-10-19-requirements-v2.md`、M6 各专项规格、`doc/2026-10-22-platform-extras.md`、`doc/2026-10-24-agent-led-framework.md`。
> 冲突处理：**本文档 + agent-led 框架文档优先**；旧文档中「引擎直接出 finding」「部署硬编码配方」「独立 retrieval 预取」不再作为目标。

## 1. 一句话定位

**CodeSentry 是基于 LangGraph 的多 Agent 源码安全审计平台：引擎把代码转成图，Agent 以图为工作记忆自主审计与部署，RAG 提供经验，PoC 提供实证。**

## 2. 五条不可妥协原则

1. **图是唯一事实源。** 引擎（Semgrep/Joern/CodeQL）和 tree-sitter 的产出统一为图节点/边/属性；引擎命中只是 hint，不是 finding。
2. **审计由 Agent 主导。** Agent 自己选择接口、追调用链、补证据；不是对扫描结果逐条 yes/no。
3. **部署由 Agent 主导。** Agent 读仓库、生成 Dockerfile、构建/启动/探测、按日志修正；配方只是工具与兜底。
4. **Agent 可配置。** 每个 Agent 的 Prompt、变量、工具白名单、Skills、LLM、预算、超时均可版本化配置。
5. **RAG 是 Agent 的工具。** 知识库/历史案例/审计模式/扫描策略按需检索，不作为强制预取阶段。

## 3. 目标链路

```
上传/仓库 → 许可 Gate
  → graph_build（tree-sitter）
  → scan（Semgrep/Joern/CodeQL → GraphDelta）
  → audit（AuditAgent：图 + 源码 + RAG 工具）
  → triage（对抗性验证，可回 audit 补查）
  → deploy（DeployAgent：规划/构建/运行/探测）
  → poc_gen（利用链 + canary 实证）
  → [human_review] → report
```

每个 Agent 是 LangGraph 子图：`plan → tool_call* → final`，带预算、超时、中断与回放。

## 4. 核心需求域

### A. 图与引擎（P0）

- 六语言 tree-sitter 结构图：文件/类/函数/方法/调用/导入/路由。
- 三引擎适配器：输出 `GraphDelta`，写入 `source/sink/dataflow/calls` 节点与边，带 `provenance`、`confidence`、`evidence`。
- 项目级增量构建：按文件 sha、`build_id`、可复现统计。
- 图查询：邻域、路径、可达、入口、finding 子图。
- 验收：真实 Java 仓库图非空；引擎贡献可在图中看到；不再直接产出最终 finding。

### B. Agent 审计（P0）

- AuditAgent：主动探索接口/参数/数据流，产出 `candidate_findings`。
- TriageAgent：对抗性验证候选（图路径、校验、可达性），输出保留/降级/否决 + 置信度 + 修复建议。
- 支持 `triage → audit` 补查（限次）。
- 候选必须带 `file:line` 与源码/图证据。
- 验收：真实仓库可由 Agent 产出候选；每条可回溯；无证据候选降级而非消失。

### C. Agent 部署（P0）

- DeployAgent：读仓库、决定构建方式、生成 Dockerfile、构建/启动/探测、按日志修正（限 2–3 次）。
- 只允许 Docker 内执行；不执行宿主 shell、不使用特权容器/宿主网络。
- `deploy_status / deploy_log / target_url / plan / tool_trace` 落库并在 UI 展示。
- 失败不阻塞报告；PoC 最高 `plausible`。
- 验收：上传 zip 后 Agent 自主尝试部署并能解释失败原因。

### D. Agent / Prompt 配置（P0）

- 内置 Agent：recon、scan、audit、triage、deploy、poc_gen、report。
- 每 Agent 可配：启停、LLM Profile、模型角色、Prompt 版本、Skills、工具白名单、预算、温度、超时、最大迭代、能力矩阵。
- Prompt 三段式：可编辑正文 + 代码固定安全/输出尾 + 运行期变量；版本化、Diff、回滚、预览、A/B。
- 扫描固定快照：Prompt/Skill/LLM/编排/规则版本。
- 验收：UI 可编辑 audit/deploy 的 Prompt 与工具白名单；改动下次扫描生效。

### E. RAG / 经验（P0/P1）

- 五类语料：代码图、知识库、历史案例、审计模式、扫描策略。
- 以工具暴露：`graph_* / kb_search / vuln_cases / audit_patterns / scan_strategies`。
- Agent 按需调用；结果带来源与相似度。
- 人工确认 finding 晋升回 `vuln_cases`。
- 验收：Audit/Triage/PoC 的 tool_trace 中可见 RAG 引用。

### F. LangGraph 运行时（P0）

- StateGraph + PostgresSaver；中断/恢复、Send 并行、子图、astream 事件、时间旅行。
- 节点级 `node_runs` + `agent_artifacts` 哈希链。
- 条件边：audit→triage、triage→audit 补查、triage→deploy、失败降级 report。
- 验收：节点可见、可中断、可恢复、可回放；WS 事件完整。

### G. 证据 / PoC / 报告（P0）

- PoC 必须带 canary（命令回显/HTTP 回调/文件副作用）；无实证最高 `plausible`。
- 四层置信度（raw/evidence/calibrated/verdict-gated）+ 校准 ECE。
- 中文 Markdown + SARIF 2.1.0；每条 finding 附证据链、图路径、修复建议、PoC 判定。
- 验收：真实样例 canary 命中；报告可回溯到 Agent 输入/输出。

### H. 控制面（P0/P1）

- LLM：多 Profile、加密掩码、优先级池、熔断/健康、原始调用记录、用量成本配额。
- Prompt/Skills/规则/编排：版本化、预览、回滚、A/B、评测。
- 身份：单租户 + admin/analyst/viewer + API Token（多租户不做）。
- 审计：配置变更、登录、PoC 执行、导出、清理留痕。
- 验收：密钥不泄露；池故障转移；配置可回滚。

### I. Web 控制台（P0/P1）

- Vue3 + Element Plus + ECharts；所有路由直接访问/刷新 200。
- 核心页：总览、扫描、扫描详情、复核、Agent、LLM、Prompt、Skills、知识库、规则、编排、审计、设置、用户。
- 图页面：力导向、过滤、节点详情、源码切片、finding/路径高亮。
- **性能要求（新增）**：首屏 <2s；大图默认降采样/折叠；表格虚拟化或分页；路由懒加载；ECharts/Element Plus 分包；避免一次性渲染 3000+ 节点造成卡顿。
- 验收：16 路由 200；大图可交互不卡；构建无类型错误。

### J. 安全红线（P0）

- PoC 仅授权本地目标；默认 `POC_RUN=off`；不保留交互 shell/反弹 shell。
- 部署容器非 root、限资源、默认禁出网、宿主端口仅 127.0.0.1。
- 密钥仅 `.env`/加密库；读接口掩码；日志/报告/导出不含完整密钥。
- 上传防路径穿越/大小限制；git 仅 https；阻断私网/回环。
- 仓库与用户输入视为不可信数据，不执行其中指令。
- 许可：发行物不含 CodeQL 二进制/受限规则包。

### K. 运维与生命周期（P1/P2）

- 健康检查、磁盘用量、容器/网络/工作区清理、保留策略。
- Webhook/通知、SDK/CLI/API 一致、配置导入导出、回放。
- 验收：删除扫描无残留；保留策略可执行。

### L. 非功能

- 六语言覆盖；可复现快照；本地数据；Docker Compose 起库；单引擎/单 LLM 失败降级；测试不依赖外网；模块边界清晰。

## 5. 当前实现对账

| 域 | 状态 | 说明 |
|---|---|---|
| 图构建/查询/UI | ✅ 基本完成 | tree-sitter 六语言、增量、图 API、力导向页 |
| 引擎→图 | 🟡 重构中 | `graph_delta.py` 已加，`scan` 改为输出 hints；需真实仓库验证 |
| AuditAgent | 🟡 重构中 | `agents/audit.py` 已加并接入节点；Prompt/工具/RAG 待联调 |
| Triage | 🟡 重构中 | 改吃 candidate；补查回边已接；测试待收敛 |
| DeployAgent | 🟡 重构中 | `agents/deploy_agent.py` 已加；Docker 工具链待真实验证 |
| RAG 工具化 | 🟡 重构中 | `kb_search/vuln_cases/patterns/strategies` 已进工具；retrieval 节点已移除 |
| Agent/Prompt 配置 | 🟡 重构中 | audit/deploy 已进注册表与 Prompt；UI 自动展示，待联调 |
| 控制面 | ✅ 大部分完成 | LLM 池/健康/原始记录、Prompt 版本/预览、Skills、编排、认证、用量 |
| 前端性能 | ❌ 未完成 | 大图/大表仍可能卡顿；需降采样、分包、虚拟化 |
| kvf 端到端 | ⏳ 待重跑 | 需在新 Agent 链路下重新验证 |

## 6. 核心验收（重构后）

1. 上传 kvf-admin：`graph_build` 产出图；`scan` 把引擎命中写入图；`audit` 产出候选；`triage` 出结论；`deploy` 给出 Agent 方案与日志；报告可追溯。
2. 图里能看到引擎贡献；最终 finding 不直接等于 `engine_findings`。
3. Audit/Deploy 的 `tool_trace` 可在 UI 查看；Prompt 可编辑并生效。
4. RAG 工具在 Agent 轨迹中可见，且不强制预取。
5. 大图（>2000 节点）默认不卡顿；页面首屏 <2s。
6. 全量测试绿；ruff/mypy 绿；前端 build 通过。

## 7. 明确不做

- 多租户/跨组织 marketplace；远程 target；交互式 shell/持久化后门；SCA/容器/IaC/DAST；自动修复补丁；IDE 插件；Skill 可执行脚本。

## 8. 待决

1. 引擎 hint 的展示层级（默认折叠/仅 Agent 可见）。
2. 大图降采样策略（按 package 折叠 vs 只显示 finding 路径）。
3. DeployAgent 允许的最大构建时长与失败重试次数。
4. 是否保留旧 `retrieval` CLI/API 兼容层（建议保留一个版本周期）。

## 9. 与旧文档的替换关系

| 旧结论 | 新结论 |
|---|---|
| `ScanAgent` 产出 `engine_findings` | 引擎产出 `GraphDelta` + hints |
| `retrieval` 是流水线节点 | RAG 是 Agent 工具，无独立节点 |
| DeployAgent 按语言配方 | Agent 规划 + Dockerfile 生成/迭代，配方为兜底 |
| 6 个 Agent | 7 个 Agent（+audit，deploy 独立） |
| Prompt 仅正文+版本 | 三段式 + 变量目录 + 工具白名单 + 预览/A/B |
