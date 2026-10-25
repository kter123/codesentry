# CodeSentry 统一审计框架 Spec（Graph × DeepAudit）

- 日期：2026-10-25
- 状态：重设计，替换“节点堆叠式”增量方案
- 目标：以代码图/路径为事实源，Supervisor 动态编排，Harness 验证，全程可查、可视化

## 1. 设计原则

1. **一个运行时**：只保留 LangGraph；不引入 DeepAudit 的第二套 ReAct 执行器。
2. **一个事实源**：代码图 + 路径；引擎、工具、RAG、Harness 只产证据，不直接产最终 finding。
3. **一个生命周期**：
   `candidate → path_audited → verified/plausible/rejected → triaged → reported`
4. **一个 Supervisor**：只做白名单动作调度，不直接下漏洞结论。
5. **一个事件模型**：所有 Agent/工具/验证/预算事件写 `agent_events`，前端可回放。
6. **一个工作台**：审计流、Agent 树、路径、finding、验证、图、报告在同一页面联动。
7. **安全默认**：PoC/网络默认关闭；无反弹/交互 shell；Harness 无网、只读、cap_drop。

## 2. 目标架构

```text
┌──────────────────────────────────────────────────────────────┐
│ Control Plane: LLM / Prompt / Agent / Knowledge / Settings   │
└─────────────────────────────┬────────────────────────────────┘
                              │
┌─────────────────────────────▼────────────────────────────────┐
│ LangGraph Runtime                                            │
│  recon → graph_build → scan → path_build                     │
│        → Supervisor ──┬─ audit_paths (Send)                  │
│                       ├─ verify_paths (Harness)              │
│                       ├─ run_tool (Gateway)                  │
│                       ├─ triage                              │
│                       └─ report                              │
│  events / controls / budget / checkpointer                   │
└─────────────────────────────┬────────────────────────────────┘
                              │
┌─────────────────────────────▼────────────────────────────────┐
│ Evidence & Analysis                                          │
│ Graph (nodes/edges) · Paths · Engine hints · Tool runs       │
│ Harness runs · RAG knowledge packs · Findings                │
└─────────────────────────────┬────────────────────────────────┘
                              │
┌─────────────────────────────▼────────────────────────────────┐
│ Vue3 Audit Workbench                                          │
│ Agent tree | Event stream | Path/Finding/Verification/Graph  │
└──────────────────────────────────────────────────────────────┘
```

## 3. 统一领域模型

### Finding 生命周期

| 状态 | 产生者 | 含义 |
|---|---|---|
| `candidate` | AuditAgent / PathAudit | 有路径/源码证据，未最终判定 |
| `path_audited` | PathAudit | 单路径结论 |
| `verified` | Harness | 运行触发 |
| `plausible` | Harness/Triage | 证据闭合但未触发/环境失败 |
| `rejected` | Triage/Harness | 不可达/已净化 |
| `reported` | Report | 进入主报告 |

### 证据类型

- `graph_path`：entry→source→sink 节点/边。
- `engine_hint`：Semgrep/CodeQL/Joern。
- `tool_evidence`：Gitleaks/Bandit/OSV 等。
- `harness_run`：代码、stdout/stderr、退出码、canary。
- `rag_evidence`：知识包/案例/模式。
- `code_slice`：file:line 源码。

## 4. Supervisor 设计

动作白名单：

```json
{"action":"audit_paths|verify_paths|run_tool|triage|report|finish",
 "reason":"...", "args":{}}
```

决策规则（确定性兜底 + 可选 LLM）：

1. budget breach → report。
2. pending proven/likely paths > 0 且未达轮次 → audit_paths。
3. audited proven paths 未验证且 Harness 开启 → verify_paths。
4. 有 candidate/verified → triage。
5. 否则 finish/report。
6. 每轮最多 N 次；无状态变化直接退出。

Supervisor 决策写 `agent_events(supervisor.decision)`。

## 5. 事件与可观测

事件类型：

```text
scan.start/end
node.start/end
supervisor.decision
thought
tool.start/result
path.claimed/path.audited/path.timeout
finding.candidate/finding.updated
verification.start/result
budget.warn/breach
report.ready
```

- `agent_events(scan_id,seq,...)` 持久化，seq 连续。
- SSE：`/api/scans/{id}/events/stream?after_seq=`，先回放再轮询。
- Agent 树：`agent_nodes` + node_runs 合并。
- 暂停/恢复/停止：`scan_controls`，节点边界检查。

## 6. Harness / 工具网关

- Harness：LLM/模板生成代码 → Docker 执行 → `HARNESS_VERIFIED`/`HARNESS_NOT_TRIGGERED`。
- 全语言：Python/JS/TS/PHP/Java/Go/Ruby/Shell；统一 `harness_image`。
- 工具网关：固定 argv、白名单、超时、无网络；结果归一化，不直接成 finding。
- 首批：Gitleaks、Bandit、OSV、npm audit、Safety。

## 7. 知识包

- `knowledge_packs`：框架/漏洞/策略，版本、来源、启停。
- 检索与 pgvector/bge-m3 融合；来源标记 `pack:name@version`。
- 不引入 ChromaDB。

## 8. 前端工作台

Vue3 + Element Plus + ECharts：

```text
顶部：状态 / 预算 / 路径覆盖 / verified / plausible / rejected / 暂停停止
左栏：Agent 树 + 阶段
中栏：审计事件流（thought/tool/finding/verification），过滤/回放/自动滚动
右栏：选中事件 → 路径链 / 源码 / 证据 / Harness / 修复
底部：路径 | Findings | 验证 | 图 | 报告
```

参考 DeepAudit 的信息密度和审计流，不复制其视觉/代码。

## 9. 安全边界

- 不做反弹/交互 shell、远程任意利用、多租户。
- Harness/工具默认无网；容器只读、cap_drop、no-new-privileges。
- 密钥/证据导出脱敏。
- 知识包/仓库/事件内容均视为不可信数据。

## 10. 验收

- 扫描运行中可看到 Agent 事件、路径 finding、验证结果。
- 刷新页面可回放事件；可暂停/恢复/停止。
- Harness 至少 Python 真实触发；其他语言命令/镜像可配置。
- 工具不可用时显示 `unavailable`，不阻断扫描。
- 工作台 3 栏联动；Playwright 通过。
- 全量 pytest/ruff/mypy/build。
