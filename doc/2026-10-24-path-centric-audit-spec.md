# 路径中心的多轮源码审计 · 设计规格

- 日期：2026-10-24
- 状态：待 spec 审计
- 关联：`doc/2026-10-24-agent-led-framework.md`、`doc/2026-10-24-requirements-core.md`
- 目标读者：实现者、审计者、前端

## 0. 问题陈述

当前 AuditAgent 是“一次性 LLM 复核”：读一遍接口与少量 hint，输出 1–2 条候选就结束。这不符合源码审计的工作方式。

真实的源码审计应当是：

1. 从引擎/图得到大量**可疑函数**（sink、危险调用、未鉴权入口、外部输入点）。
2. 对每个可疑点**反向推导攻击路径**：哪些入口/参数能到达它；正向确认 source 是否可控。
3. 把每条**路径**作为独立审计工作项，逐条读源码、补证据、判定。
4. 对确认/可疑路径**继续扩展**：同 sink 的其他入口、同入口的其他 sink、调用链上下游、兄弟分支。
5. 部署后对**每条可利用路径**生成 PoC 并做 canary 实证，而不是只对一条 finding 生成 PoC。
6. 多轮推进，直到路径队列收敛、覆盖率达标或预算耗尽。

## 1. 目标

- 每条可疑函数都能被至少一条路径覆盖；路径有入口、source、sink、完整节点/边序列。
- 审计按路径并行/分批执行，支持多轮扩展；一轮结束不是审计结束。
- 每条 finding 绑定 `path_id`，报告/PoC/UI 都能回溯到路径。
- 部署后按路径生成 PoC 并验证；验证结果回写路径。
- 覆盖率、轮次、队列、预算可见；可在 UI 查看“已审计/待审计/排除”的路径。

## 2. 非目标

- 不做全量符号执行或完备污点分析；路径来自图 + 启发式 + Agent。
- 不做远程目标利用；PoC 仅本地授权容器。
- 不保证零漏报；以覆盖率与证据链为目标。

## 3. 数据模型

### 3.1 `audit_paths`

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `scan_id` | 扫描 |
| `path_key` | `sha256(entry|source|sink|nodes)`，去重 |
| `round` | 发现轮次（0 为初始） |
| `kind` | `entry_to_sink` / `source_to_sink` / `sibling` / `neighbor` |
| `entry_key` | 入口 endpoint/route/function |
| `source_key` | 可控输入节点（可空） |
| `sink_key` | 可疑 sink 节点 |
| `nodes` | 有序节点 key JSONB |
| `edges` | 有序边 JSONB |
| `length` | 节点数 |
| `score` | 排序分（0–1） |
| `status` | `pending/auditing/finding/clean/blocked/error` |
| `finding_id` | 关联 finding（可空） |
| `evidence` | 审计证据 JSONB |
| `created_at/updated_at` | 时间 |

索引：`(scan_id,status,round)`、`(scan_id,sink_key)`、`(scan_id,entry_key)`、唯一 `(scan_id,path_key)`。

### 3.2 `audit_rounds`

| 字段 | 说明 |
|---|---|
| `scan_id, round` | 主键 |
| `paths_total/new/audited/findings` | 统计 |
| `started_at/finished_at` | 时间 |
| `stop_reason` | `converged/budget/limit/error` |

### 3.3 state 扩展

```python
audit_paths: list[dict]      # 本轮待审路径（Send payload）
path_results: Annotated[list[dict], operator.add]
audit_round: int
coverage: dict               # endpoints/sinks/paths 覆盖
```

## 4. 路径构建

### 4.1 种子

- 图 `sink` 节点（引擎 hint + tree-sitter sink）。
- `source` 节点。
- `endpoint` 节点，按权限（内部接口/公开优先）。
- 危险函数名表（exec/eval/system/readObject/Statement/…）作为补充。

### 4.2 反向路径

对每个 sink：

1. 沿 `calls` / `taints_to` 反向 BFS，深度 ≤ `PATH_DEPTH`（默认 8）。
2. 命中 `route/endpoint` 或函数参数为 source 的节点即为路径起点。
3. 同时从 `source` 正向 BFS 到 sink，取交集路径。
4. 产出 `entry_to_sink` 或 `source_to_sink` 路径；每条保存完整节点/边序列。

### 4.3 评分

`score = 0.35*sink_severity + 0.2*entry_permission + 0.2*source_controllable + 0.15*short_path + 0.1*taint_edge`

排序后入队；默认上限 `MAX_PATHS=2000`。

### 4.4 去重

- `path_key` 去重；同一 (entry,sink) 仅保留最短且分数最高的 3 条。
- 已在 `clean/blocked` 的路径不重复入队，除非新一轮有新边。

### 4.5 路径可行性与证据等级

图里的 `calls` 边不等于“参数可控地流到 sink”。每条路径必须标注证据等级：

| 等级 | 条件 | 审计策略 |
|---|---|---|
| `proven` | 存在连续 `taints_to` 边，或 source 与 sink 在同一函数且参数被直接使用 | 优先审计，可直接判 finding |
| `likely` | entry→…→sink 调用链闭合，但跨函数参数映射是启发式（参数名/位置匹配） | 需要 Agent 读源码确认参数传递 |
| `weak` | 只有文件/包含关系或引擎 hint，没有调用边 | 仅作补充，默认低优先级 |

路径表新增 `feasibility` 字段（`proven/likely/weak`），评分乘以系数 `1.0/0.75/0.4`。审计输出必须说明是否确认了跨函数参数流。

### 4.6 图不完整时的兜底

- 引擎 hint 无法锚定函数时，以 `file` 级节点 + `line` 生成 `weak` 路径，仍进入队列但低优先级。
- 跨文件调用未解析时，允许用“同文件 + 相邻行 + 参数名匹配”建 `likely` 路径，并在证据中标注 `heuristic=true`。
- 报告中展示 `unresolved_calls`，避免把“图里没有”误判为“不可达”。

## 5. 多轮审计

```
round 0: path_build → pending paths
loop:
  dispatch: 取 N 条 pending（按 score），Send 到 audit_path
  audit_path: 单路径 Agent 审计 → finding/clean/blocked + 证据
  collect: 写回状态；对 finding/可疑路径生成下一轮路径
  if 无新路径 or round>=MAX_ROUNDS or budget breach or no pending: stop
```

### 5.1 单路径审计

输入：路径节点序列、edges、代码切片（每节点 ≤200 行）、入口权限、source 可控性、引擎 hint、RAG（vuln_cases/patterns）。

输出：

```json
{"verdict":"finding|clean|blocked|need_more",
 "confidence":0.0-1.0,
 "cwe":78,"severity":"high",
 "reason":"...",
 "evidence":[{"file":"...","line":1,"snippet":"..."}],
 "fix_advice":"..."}
```

`need_more` → 路径标 `pending`，下一轮换更深/更宽路径。

### 5.2 扩展规则

对 `finding` 或 `need_more`：

1. 同 sink 的其他入口（反向 BFS 的其他分支）。
2. 同入口可达的其他 sink（正向 BFS）。
3. sink 的 callers/callees 一跳。
4. 同函数的兄弟路径（同参数、不同分支）。
5. 新路径 `round+1`，`kind=sibling|neighbor`，去重后入队。

### 5.3 并发与预算

- `AUDIT_CONCURRENCY`（默认 4）；LangGraph `Send` 分批。
- 单路径 LLM 预算、扫描总预算；80% 预警，100% 停止扩展并出报。
- 每路径写 `node_runs`/`agent_artifacts`，含 path_id。
- **认领**：dispatch 用 `UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED)` 把路径置 `auditing`，避免并发重复审计。
- **超时回收**：`auditing` 超过 `PATH_LEASE_S`（默认 900s）自动回 `pending`，计入重试次数；超过 2 次置 `error`。
- **幂等**：同一 path_key 的审计结果按 `(path_id, round)` upsert；断点续跑从 `pending` 继续。

### 5.4 上下文预算

单路径送入 Agent 的源码切片总量 ≤ 24KB；每个节点最多 120 行，优先入口、source、sink 三个节点。超出时只保留关键行并标注“已截断”。

## 6. Triage / 部署 / PoC

- Triage 按路径结果逐条验证；finding 必须绑定 path_id。
- 部署在 triage 之后、PoC 之前；DeployAgent 产出 target_url。
- PoC 按路径生成：入口 URL/参数 → 路径上的传播 → sink；canary 占位符；验证结果回写 path/finding。
- 报告每条 finding 附路径节点/边与验证级别。

## 7. LangGraph 拓扑

```
recon → graph_build → scan → path_build
      → audit_dispatch ⇄ audit_path (Send) → audit_collect
      → triage → deploy → poc_paths → human_review → report
```

- `audit_dispatch` 条件边：有 pending 且预算允许 → 继续；否则 → triage。
- `audit_collect` 生成新路径后回到 dispatch。
- `poc_paths` 按 finding/path 并行（Send，可选）。

## 8. UI

- 扫描详情新增「审计路径」tab：
  - 覆盖率卡片：入口覆盖、sink 覆盖、路径总数/已审/待审/排除、轮次。
  - 路径表格：入口、source、sink、分数、轮次、状态、finding。
  - 点击路径 → 图视图高亮节点/边；显示代码切片与证据。
- 图页面支持 `?path_id=` 高亮。
- 实时事件：`audit.round.start/end`、`audit.path.start/end`。

### 8.1 API

| 端点 | 说明 |
|---|---|
| `GET /api/scans/{id}/paths?status=&round=&limit=` | 路径列表 |
| `GET /api/scans/{id}/paths/{path_id}` | 路径详情（节点/边/证据/slices） |
| `GET /api/scans/{id}/coverage` | 覆盖率与轮次统计 |
| `POST /api/scans/{id}/audit/expand` | 手动追加一轮扩展（可选） |

## 8.2 事件

- `audit.round.start {round, pending}`
- `audit.path.start {path_id, entry, sink}`
- `audit.path.end {path_id, verdict}`
- `audit.round.end {round, audited, findings, new_paths}`

## 9. 配置

| 配置 | 默认 | 说明 |
|---|---|---|
| `PATH_DEPTH` | 8 | 反向/正向 BFS 深度 |
| `MAX_PATHS` | 2000 | 入队上限 |
| `AUDIT_CONCURRENCY` | 4 | 并发路径数 |
| `AUDIT_MAX_ROUNDS` | 3 | 最大扩展轮次 |
| `AUDIT_BATCH` | 8 | 每批路径数 |
| `PATH_MIN_SCORE` | 0.2 | 低于不入队 |

## 10. 验收

1. 合成 Java/Python 仓库：至少产出 3 条 entry→sink 路径；审计后至少 1 条 finding，绑定 path_id。
2. kvf-admin：路径数 > 10；审计轮次 ≥ 2；**候选 finding 数 ≥ 3**（允许 Triage 最终 demote/reject）；每条候选绑定路径与证据。
3. 部署成功后，至少 1 条路径生成 PoC 并 canary 验证（或明确失败原因）。
4. UI 路径 tab 可用；图高亮路径。
5. 全量测试绿；OpenCode Go 真实 Agent 多轮测试通过。
6. 断点续跑：中断后重新启动，未完成路径继续审计，不重复已 `clean/blocked` 路径。

## 11. 风险

| 风险 | 缓解 |
|---|---|
| 路径爆炸 | 上限、评分、每 (entry,sink) 限 3 条、预算 |
| 图不完整导致路径缺失 | 引擎/ tree-sitter 互补；报告标注“未解析调用” |
| LLM 成本高 | 批量、并发、预算、短路径优先、缓存 |
| 误报 | Triage 对抗验证 + 证据门槛 + 人工复核 |
| 长任务 | 队列持久化、断点续跑、批次事件 |
