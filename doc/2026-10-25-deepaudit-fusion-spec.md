# DeepAudit × CodeSentry 融合需求与总体设计（评审稿）

- 日期：2026-10-25
- 状态：**设计评审，不执行代码**
- 参考：`DeepAudit/`（AGPL-3.0，仅借鉴概念，不复制代码/Prompt/规则）
- 目标：吸收 DeepAudit 的 Harness 验证、Agent 编排和前端体验，强化 CodeSentry 的图/路径审计主链

## 1. 背景与判断

DeepAudit 的核心价值不在“又一个 SAST”，而在三件事：

1. **LLM Orchestrator 真正做调度**：ReAct 循环，动态决定调用 Recon/Analysis/Verification。
2. **Verification Harness**：提取函数、mock 依赖、多 payload、沙箱执行，用运行结果确认漏洞。
3. **Agent 可观测产品化**：Agent 树、实时事件流、思考/工具/发现日志、报告导出。

CodeSentry 的优势是：

- 代码图/路径是一等公民；
- 引擎结果转图增量，不直接作为最终结论；
- 路径级多轮审计、entry→sink、entry-only 覆盖；
- LangGraph StateGraph + Send 并行 + checkpointer；
- 图 UI、路径 UI、复核、Prompt/LLM 控制面。

融合方向：

> **图/路径负责“可能在哪里”，Harness 负责“是否真的能触发”，Supervisor 负责“下一步做什么”。**

## 2. 目标与非目标

### 目标

- 在现有 CodeSentry 路径审计中增加 Harness 验证阶段。
- 引入 Supervisor Agent 做有限、可审计的动态调度，而不是写死主链。
- 建立统一 Agent 事件流/Agent 树，前端可实时观察。
- 建立工具网关，接外部安全工具但结果只作为证据/图 hint。
- 前端从“页面集合”升级为“审计工作台”。
- 保持多租户不做、远程任意利用不做、反弹/交互 shell 不做。

### 非目标

- 不替换 LangGraph，不引入 DeepAudit 的第二套 Agent 执行器。
- 不引入 ChromaDB，不建第二套向量库。
- 不复制 DeepAudit 的 AGPL 代码、Prompt 原文、规则文件。
- 不把外部工具结果直接当最终 finding。
- 不自动修改用户源码；修复建议只产 patch。

## 3. 目标架构

```text
recon
  ↓
graph_build
  ↓
scan（Semgrep / CodeQL / Joern → graph hints）
  ↓
path_build（entry→sink / entry-only）
  ↓
supervisor ───────────────┐
  ├─ path_audit（Send 并行）│
  ├─ tool_evidence          │
  ├─ harness_verify         │
  ├─ deploy（Web 目标）     │
  ├─ poc                    │
  └─ triage                 │
        ↓                   │
      report ←──────────────┘
```

### Supervisor 的职责

Supervisor 不直接读源码做结论，只做调度决策：

```json
{
  "action": "audit_paths|run_tool|verify_finding|deploy|poc|triage|report|finish",
  "reason": "为什么下一步做这个",
  "args": {}
}
```

约束：

- 动作白名单，不能自由生成节点。
- 每个动作有预算、超时、最大次数。
- path finding 必须有路径证据；entry-only 只能做鉴权/参数审计。
- Supervisor 不能跳过 path_build 直接报漏洞。
- 到达预算/轮次/覆盖阈值后强制进入 triage/report。

### Agent 角色

| Agent | 职责 | 与现有代码关系 |
|---|---|---|
| Supervisor | 动态调度、预算/轮次控制 | 新增 LangGraph 节点 |
| Recon | 技术栈、入口、依赖 | 复用并增强 |
| GraphBuild | 六语言图 | 复用 |
| Scan | 引擎→图 hint | 复用 |
| PathAudit | 单路径审计 | 复用 |
| ToolEvidence | 外部工具证据 | 新增 |
| HarnessVerify | 函数提取、mock、沙箱 | 新增 |
| Triage | 结论/降级/否决 | 复用，增加 verified 维度 |
| Deploy/PoC | Web 目标/PoC | 复用 |
| Report | 报告 | 复用并增强 |

## 4. Harness 验证子系统

### 4.1 流程

```text
path/finding
  → 定位 sink 所在函数/方法
  → extract_function（源码 + 依赖 + 行号）
  → 选择漏洞模板（CWE → harness 模板）
  → LLM 生成 harness（可选模板填充）
  → 静态安全检查（禁止 shell 外联/破坏性操作）
  → Docker 沙箱执行
  → 输出分类：触发/未触发/环境失败
  → 写 verification_runs + evidence
  → finding.verdict = verified/plausible/rejected
```

### 4.2 Harness 类型

| CWE | 模板 | 检测方式 |
|---|---|---|
| 78 命令注入 | mock `os.system/exec/subprocess` | 记录被调用命令 + canary |
| 89 SQL 注入 | mock cursor/ORM | 检测拼接/无参数化 |
| 79 XSS | 渲染函数 | payload 是否原样输出 |
| 22 路径遍历 | mock 文件系统 | 是否逃逸 root |
| 94/95 代码注入 | mock eval/exec | 是否执行 |
| 502 反序列化 | mock loader | 是否调用危险反序列化 |
| 918 SSRF | mock HTTP client | 是否请求外部/内网 |
| 611 XXE | mock XML parser | 是否解析外部实体 |
| 1333 ReDoS | 正则执行 | 超时/回溯 |

### 4.3 沙箱策略

- Docker，一次性容器，执行后删除。
- `network=none` 默认；需要 HTTP 验证时显式 `bridge` + 目标白名单。
- `read_only=true`，临时目录 tmpfs。
- `cap_drop=ALL`，`no-new-privileges`。
- 内存/CPU/超时限制。
- 不允许宿主 Docker socket 暴露给 harness 代码。
- 输出截断、日志脱敏。

### 4.4 判定策略

DeepAudit 的“PoC 失败直接丢弃”过于激进。CodeSentry 采用：

- `verified`：harness 明确触发（canary/输出/副作用）。
- `plausible`：路径/代码证据闭合，但环境无法运行或 harness 不充分。
- `rejected`：明确不可达/已净化/误报。
- 报告默认把 `verified` 单列，`plausible` 降级展示，`rejected` 不进主报告。

### 4.5 数据模型

```text
harness_templates(id, cwe, language, name, template, enabled, version)
verification_runs(id, scan_id, path_id, finding_id, cwe, language,
                  harness_code, status, verdict, exit_code, stdout, stderr,
                  evidence, duration_ms, created_at)
tool_runs(id, scan_id, tool, args, status, result, duration_ms, cost, created_at)
agent_events(id, scan_id, seq, agent, event_type, payload, created_at)
agent_nodes(id, scan_id, parent_id, agent, phase, status, started_at, ended_at,
            tokens, tool_calls, summary)
```

## 5. Agent 编排设计

### 5.1 保留 LangGraph

- Supervisor 是一个 LangGraph 节点，不是新执行器。
- 子 Agent 用 LangGraph 子图或节点函数。
- 并行审计继续用 `Send`。
- checkpointer 继续用 PostgresSaver。

### 5.2 事件模型

统一事件：

```text
agent.start / agent.end
thought
tool.start / tool.end
handoff
finding.new / finding.updated
verification.start / verification.result
sandbox.start / sandbox.result
budget.warn / budget.breach
report.ready
```

事件写入 `agent_events`，SSE 按 `seq` 断点续传。

### 5.3 控制能力

- 暂停/恢复：checkpointer + interrupt。
- 停止：取消标志 + 子任务取消。
- 向 Agent 发消息：写入 `agent_messages`，Supervisor 下一轮读取。
- Agent 树：parent/child、状态、tokens、当前工具。

## 6. 工具网关

统一注册：

```json
{
  "name": "semgrep_scan",
  "languages": ["python", "java", "js"],
  "requires_docker": true,
  "network": false,
  "timeout_s": 300,
  "output_schema": "findings|secrets|deps",
  "evidence_kind": "sink|secret|dependency"
}
```

工具结果不直接成为 finding：

```text
tool result → normalize → evidence record → graph hint / path sink
```

优先接：

- Semgrep（已有）
- CodeQL（已有）
- Joern（已有）
- Gitleaks
- Bandit
- OSV-Scanner
- npm audit / Safety
- Kunlun-M（PHP/JS）

## 7. 前端设计

### 7.1 信息架构

现有页面保留，新增/强化：

```text
概览
审计工作台（新，核心）
扫描管理
项目与定时
复核队列
知识库
Agent / Prompt / LLM
设置
```

### 7.2 审计工作台布局

```text
┌──────────────────────────────────────────────────────────────┐
│ 顶部：扫描状态 · 预算 · 路径覆盖 · verified/plausible/rejected │
├──────────────┬──────────────────────────────┬────────────────┤
│ 左：阶段/树   │ 中：实时审计流                │ 右：上下文      │
│ Recon        │ Thought / Tool / Finding     │ 路径节点        │
│ GraphBuild   │ Verification / Sandbox       │ 源码切片        │
│ Scan         │ 可过滤、可暂停、可回放        │ 证据/Harness    │
│ PathAudit    │                              │ 操作按钮        │
│ Verify       │                              │                │
├──────────────┴──────────────────────────────┴────────────────┤
│ 底部 tabs：路径 | Findings | 验证 | 图 | 报告                 │
└──────────────────────────────────────────────────────────────┘
```

### 7.3 增量落库与实时可观测（新增，优先修复）

当前 `/api/scans/{id}/findings` 只读 `findings` 表，而路径审计的中间结果在 `audit_paths.evidence`；只有扫描结束才统一写 `findings`。这会造成“Agent 明明在跑，UI 看不到”的错觉。

要求：

- `run_audit_path` 完成时立即 upsert `findings`（按 `scan_id+path_id` 唯一），不再等扫描结束。
- `/api/scans/{id}/findings` 增加 `source=live|final`，运行中返回 Agent 中间 finding。
- 扫描详情顶部显示：路径已审/总数、finding 数、agent tokens、超时数、当前批/轮。
- 事件流增加 `finding.new`、`path.audited`、`path.timeout`、`agent.thought`。
- Agent 即使 `tool_calls=0`，也要记录 LLM 输出摘要与耗时，证明 Agent 确实参与。
- 超时路径写 `status=timeout`，不无限 pending；超时原因可见。

### 7.4 关键交互

- 点击 finding → 右侧显示路径链、源码、Harness 结果、修复 patch。
- 点击路径 → 图高亮。
- 点击 Agent 节点 → 过滤该 Agent 的事件。
- 事件流支持按类型/Agent/严重度过滤。
- 支持“仅看 verified”。
- 支持导出报告/证据包。
- 扫描运行中显示阶段进度、token/成本、剩余预算。

### 7.4 视觉方向

- 保留 CodeSentry 现有 Vue3 + Element Plus，不整体换 React。
- 借鉴 DeepAudit 的“终端审计流”信息密度，但不复制视觉皮肤。
- 暗色模式优先，日志区域等宽字体。
- 大图、长日志用虚拟滚动/分页，避免卡顿。

## 8. 分阶段计划

### Phase 1：Harness MVP + 可观测性修复

- 先做增量 finding 落库、运行中 findings API、路径审计进度/超时可见。
- 再做 Harness 表、模板、sandbox runner。

- 数据库表、模板、sandbox runner。
- Python/JS/Java 的命令注入、SQLi、路径遍历、XSS。
- API：`POST /api/findings/{id}/verify`、`GET /api/scans/{id}/verifications`。
- 前端：finding 抽屉增加“验证”与结果。
- 验收：至少 3 个 synthetic 案例 verified；误报下降可量化。

### Phase 2：Supervisor + 事件流

- Supervisor 节点、动作白名单、预算/轮次。
- `agent_events`、SSE 断点续传。
- 审计工作台 MVP。
- 验收：一次扫描可看到完整 Agent 流；可暂停/恢复。

### Phase 3：工具网关

- 工具注册表、证据归一化。
- Gitleaks/Bandit/OSV 等接入。
- 前端工具证据展示。

### Phase 4：知识包

- 框架/漏洞知识包，版本化、来源、启停。
- 与 pgvector/bge-m3/GraphRAG 融合，不引入 ChromaDB。

### Phase 5：产品化

- 项目导入、即时分析、Dashboard 指标、PDF/HTML 报告。
- Agent 树、事件回放、证据包导出。

## 9. 验收指标

- verified 比例：proven 路径中成功 harness 验证比例。
- 误报下降：Triage 后进入主报告的 false positive 比例。
- 路径覆盖：entry/sink 覆盖与 entry-only 数量。
- Harness 成功率：环境失败/超时/代码错误分类。
- 前端：审计工作台可观察、可过滤、可暂停、可跳转图。
- 性能：单路径验证超时可控，扫描总预算不失控。

## 10. 风险

| 风险 | 应对 |
|---|---|
| Harness 生成不稳定 | 模板 + LLM 混合；失败降级 plausible |
| 沙箱逃逸/外联 | network=none、cap_drop、只读、超时 |
| Agent 乱调度 | 动作白名单 + 预算 + 轮次 + 覆盖阈值 |
| 事件流过大 | 分页/seq/过滤/截断 |
| 前端过重 | 虚拟滚动、按需加载、分 tab |
| AGPL 污染 | clean-room，仅概念借鉴 |
| 误判 verified | canary/多 payload/独立 detector，不只看出 exit code |

## 11. 待确认

1. Harness 首批语言：Python/JS/Java，还是加 PHP/C？
2. 是否允许 harness 联网做 SSRF/HTTP 验证？默认应关闭。
3. 前端是否保留 Vue3，还是新审计工作台单独做 React 微前端？
4. verified 是否必须进入报告主列表，plausible 是否保留？
5. 外部工具首批接哪些：Gitleaks/Bandit/OSV 是否足够？
