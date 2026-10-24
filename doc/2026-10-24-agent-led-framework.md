# Agent 主导的源码审计框架（重梳理）

- 日期：2026-10-24
- 性质：架构重构基线，待确认后进入实现
- 替换关系：与 `agent.md` §7.2「ScanAgent 产出 engine_findings」、`requirements-v2` FR-2/FR-15 的硬编码配方冲突处以本文档为准

## 1. 需求重新解读

CodeSentry 不是「三引擎扫描 + LLM 复核」，而是：

> **以代码图为共享工作记忆、由 LangGraph 编排多个 Agent、由 Agent 自主决定审计路径与部署方式的源码审计系统。**

四条硬约束：

1. **引擎是图构建器，不是告警源。** Semgrep / Joern / CodeQL 的输出必须归一为图节点、边、属性（source/sink/调用/数据流/路由/权限），交给 Agent 分析；引擎命中最多作为 `hint` 锚点，不能直接变成 finding。
2. **审计由 Agent 主导。** Agent 自己决定看哪些接口、追哪条链、是否需要更多证据；不是对引擎结果做逐条 yes/no。
3. **部署由 Agent 主导。** DeployAgent 自己读仓库、决定构建方式、生成 Dockerfile、构建/启动/探测、根据日志修正；内置配方只作为工具与兜底。
4. **Prompt 全可配置。** 每个 Agent 的 Prompt、变量、工具白名单、Skills、LLM、预算都可版本化配置；代码只保留不可编辑的安全/输出契约尾。

## 2. 现状与目标的偏差

| 环节 | 现状 | 目标 |
|---|---|---|
| 引擎 | `agents/scan.py` 直接把引擎结果变成 `engine_findings` | 引擎产出 `GraphDelta`（节点/边/属性），图是唯一事实源 |
| 代码审计 | 无 AuditAgent；`triage` 只验证引擎命中 | AuditAgent 主动探索图与源码，产出候选 finding |
| 降噪 | Triage 只看引擎 finding | Triage 对候选 finding 做对抗性验证（图路径 + 源码） |
| 部署 | `sandbox/deploy.py` 按语言硬编码配方 | DeployAgent 用工具规划/生成/构建/运行/修正；配方为兜底 |
| 编排 | 固定 `recon→graph_build→scan→retrieval→triage→deploy→poc` | Agent 子图 + 工具循环 + `Send` 并行 + 条件回边 |
| Prompt | 仅 6 个 Agent；deploy 无 Prompt | 所有 Agent（含 audit/deploy）Prompt 版本化、变量化 |
| 图 | 自建 tree-sitter 图；引擎结果不进图 | 三引擎 + tree-sitter 统一写入图，带 `provenance` |

## 3. 目标架构

```
上传/仓库
   │
   ▼
[Ingestion] 解压/识别/许可 Gate
   │
   ▼
[Graph Construction]  ← 工具层（确定性，可被 Agent 调用）
   ├─ tree-sitter 结构图（文件/类/函数/调用/导入）
   ├─ Semgrep 适配器 → source/sink/模式节点
   ├─ Joern 适配器   → CPG 调用边/数据流边/方法节点
   └─ CodeQL 适配器  → 数据流/污点边（OSS）
   │
   ▼
[Audit Loop · LangGraph]
   ├─ ReconAgent     ：仓库/框架/入口/接口面
   ├─ AuditAgent     ：沿图探索，产出候选 finding
   ├─ TriageAgent    ：对抗性验证候选（路径/校验/可达性）
   ├─ DeployAgent    ：规划并执行部署，产出 target_url
   ├─ PoCAgent       ：基于图路径与部署目标生成/验证 PoC
   └─ ReportAgent    ：汇总证据链与报告
   │
   ▼
[Human Review] interrupt/resume → 报告

         ┌──────────────────────────────────────┐
         │  Experience / RAG 工具层（Agent 按需调用）│
         │  graph_query · kb_search · vuln_cases   │
         │  audit_patterns · scan_strategies       │
         └──────────────────────────────────────┘
```

关键点：**Graph Construction 是工具，不是决策者；审计与部署的决策在 Agent；RAG 经验库是 Agent 的工具/长期记忆，不是独立的“检索阶段”。**

## 4. 图模型（唯一事实源）

节点：`repo / package / file / class / function / method / route / endpoint / source / sink / dependency / external`

边：`contains / imports / calls / inherits / implements / routes_to / exposes / reads / writes / taints_to / depends_on`

每条节点/边必须带：

- `provenance`：`tree_sitter | semgrep | joern | codeql | agent`
- `confidence`
- `evidence`（文件:行号、规则/查询 ID、代码片段）
- `build_id`

引擎适配器输出 `GraphDelta`，由 `graph_apply(delta)` 幂等写入；不允许引擎直接写 `findings`。

## 5. Agent 定义

| Agent | 职责 | 主要工具 | 输出 |
|---|---|---|---|
| ReconAgent | 语言/框架/构建/入口/接口面 | repo_tree、read_file、graph_entrypoints、graph_search、scan_strategies | `profile` + `entrypoints` |
| AuditAgent | 主动审计：接口→参数→数据流→sink | graph_*、read_source、search_code、kb_search、vuln_cases、audit_patterns | `candidate_findings` |
| TriageAgent | 对抗性验证：可达性/校验/误报 | graph_paths、graph_neighbors、read_source、vuln_cases、audit_patterns | `triaged_findings` |
| DeployAgent | 读仓库→定方案→写 Dockerfile→构建/启动/探测→修正 | repo_tree、read_file、write_dockerfile、docker_build、docker_run、probe、logs、scan_strategies | `deploy{status,target_url,plan,trace}` |
| PoCAgent | 利用链与 canary PoC | graph_paths、read_source、vuln_cases、deploy 目标 | `poc_results` |
| ReportAgent | 证据链报告 | artifacts、graph、findings | Markdown/SARIF |

每个 Agent 都是 LangGraph 子图：`plan → tool_call* → final`，带最大迭代、预算、超时、中断点。

### 5.1 RAG / 经验层（Agent 的工具，不是独立阶段）

现有五类语料统一暴露为只读工具：

| 语料 | 内容 | 典型使用者 |
|---|---|---|
| 代码图 `graph_*` | 调用、数据流、接口、source/sink | Recon / Audit / Triage / PoC |
| 知识库 `kb_search` | CWE/OWASP、内部规范、框架安全文档 | Audit / Triage |
| 历史案例 `vuln_cases` | 已确认漏洞的链路、PoC、修复 | Audit / Triage / PoC |
| 审计模式 `audit_patterns` | 漏洞模式、规则模板、查询语料 | Audit / Triage |
| 扫描策略 `scan_strategies` | 相似项目的引擎组合与扫描计划 | Recon / Deploy |

约束：

1. 不设强制 `retrieval` 预取节点；Agent 在需要时调用工具，避免把无关证据塞进上下文。
2. 工具返回必须带来源（文件/行号/案例 ID/规则 ID）与相似度分数。
3. 经验库只提供参考，最终结论必须由当前仓库的源码/图路径支撑。
4. 人工确认的 finding 通过 `promote` 回写 `vuln_cases`，形成越用越准的闭环。

## 6. Prompt 与配置模型

- `agents` 表：key、role、enabled、LLM Profile、model role、timeout、max_iterations、budget、tools_allow、skills_allow。
- `prompt_versions`：可编辑正文 + `note/updated_by`，模板变量 `{{var}}` 严格渲染。
- 代码固定尾（不可编辑）：安全边界、证据标准、输出 JSON 契约。
- `prompt_vars`：变量目录，UI 可插入/预览。
- 每个 Agent 的 Prompt 必须能回答：目标、可用工具、证据门槛、禁止事项、输出格式。

## 7. LangGraph 编排

- 节点：`recon / graph_build / audit / triage / deploy / poc_gen / human_review / report`。
- **移除独立 `retrieval` 节点**：RAG 作为 `kb_search / vuln_cases / audit_patterns / scan_strategies` 工具由 Agent 按需调用。
- `scan` 不再是 finding 生产节点，拆为 `graph_build`（引擎适配 + tree-sitter）+ 可选 `engine_hints`。
- `audit` 可用 `Send` 按接口/子系统并行；`triage` 可按 candidate finding 并行。
- 条件边：`audit → triage`、`triage → audit`（补查，限次）、`triage → deploy`、`deploy → poc`、失败降级报告。
- 所有节点写 `node_runs` + `agent_artifacts`（plan、tool_trace、graph_delta 摘要、RAG 引用、LLM 元数据）。

## 8. 部署 Agent 的执行边界

DeployAgent 可以：

- 读仓库、列文件、读构建文件；
- 在 `.codesentry/deploy/<scan>/` 生成 Dockerfile；
- 调 `docker_build` / `docker_run` / `logs` / `probe`；
- 根据失败日志重写 Dockerfile 并重试（限 2–3 次）。

不可以：

- 在宿主执行任意 shell；
- 使用特权容器、宿主网络、越权挂载；
- 修改被测源码；
- 访问未授权外部目标。

工具层负责强制这些边界；Agent 只做决策。

## 9. 迁移阶段

| 阶段 | 内容 | 验收 |
|---|---|---|
| P1 | 引擎适配器：Semgrep/Joern/CodeQL → GraphDelta；`scan` 改为 `graph_build` | 图里能看到引擎贡献的 source/sink/dataflow 边；不再直出 findings |
| P2 | RAG 工具层：kb/vuln_cases/patterns/strategies 暴露为 Agent 工具；移除独立 retrieval 预取 | Agent 可按需检索经验；上下文只包含它主动请求的证据 |
| P3 | AuditAgent + `audit` 节点 + graph 工具完善 | kvf 等真实仓库产出候选 finding；每条带图路径/源码 |
| P4 | Triage 改为验证候选；支持 `triage→audit` 补查 | 误报下降；无证据候选降级而非直接消失 |
| P5 | DeployAgent + docker 工具 + 配置化 Prompt | 上传 zip 后 Agent 自主选择 Maven/Dockerfile/… 并尝试部署 |
| P6 | Prompt/Agent 控制面扩展 audit/deploy；UI 展示 plan/tool_trace/RAG 引用 | Agent 页面可编辑 Prompt、工具白名单、预算 |
| P7 | kvf-admin 端到端基础测试 | 上传→图→审计→部署→PoC→报告全链路可观察 |

## 10. 待确认决策

1. **引擎 hint 是否保留？** 建议保留为 `hint` 节点/属性，供 AuditAgent 参考，但不进入最终 finding。
2. **graph_build 是否 Agent 化？** 建议保持确定性工具（构建图），Agent 负责分析；否则图构建不可复现。
3. **部署自治程度？** 建议允许 Agent 生成 Dockerfile 并迭代构建，但只在 Docker 内执行；不授予宿主 shell。
4. **Audit 与 Triage 是否合并？** 建议分开：Audit 负责发现，Triage 负责证伪，保留对抗性。
5. **现有硬编码配方去留？** 保留为 DeployAgent 的 fallback 工具，不作为主路径。

## 11. 验收标准（重构后）

- 上传 kvf-admin zip：Agent 自主产出部署方案（或明确失败原因），`deploy.plan` 与 `tool_trace` 可在 UI 查看。
- 图包含引擎贡献的节点/边；`engine_findings` 为空或不作为最终结论。
- AuditAgent 至少产出候选 finding，且每条能回溯到图路径/源码。
- 所有 Agent 的 Prompt 可在 UI 编辑、预览、回滚；deploy/audit 也在列。
- 全链路 LangGraph 节点可见、可中断、可恢复、可回放。
