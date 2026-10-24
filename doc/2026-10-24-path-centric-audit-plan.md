# 路径中心审计 · 实现计划

- 面向：未见过本仓库的实现者
- 规格：`doc/2026-10-24-path-centric-audit-spec.md`（必读）
- 前置：`doc/2026-10-24-agent-led-framework.md`

## 全局约束

- LangGraph 节点保持 `state -> partial update`；副作用在节点内。
- 每路径审计写 `node_runs`/`agent_artifacts`（含 path_id）。
- 路径认领用 `FOR UPDATE SKIP LOCKED`；lease 900s。
- 单路径源码上下文 ≤24KB；每节点 ≤120 行。
- 默认 `MAX_PATHS=2000`、`PATH_DEPTH=8`、`AUDIT_BATCH=8`、`AUDIT_CONCURRENCY=4`、`AUDIT_MAX_ROUNDS=3`。
- 不得绕过预算；预算 breach 停止扩展。
- 引擎 hint 只入图/路径，不直接成为 finding。

---

## 任务 1：数据模型与状态

**文件**
- 修改：`src/codesentry/db/ddl.py`
- 修改：`src/codesentry/agents/state.py`
- 修改：`src/codesentry/config.py`

**步骤**
- [ ] `audit_paths` / `audit_rounds` DDL，索引与唯一约束。
- [ ] `AuditState` 增加 `audit_paths`、`path_results`（`Annotated[list, operator.add]`）、`audit_round`、`coverage`。
- [ ] 配置项 `path_depth/max_paths/audit_batch/audit_concurrency/audit_max_rounds/path_min_score/path_lease_s`。
- [ ] 测试：`tests/test_ddl.py` 断言表存在；`test_state_llm.py` 字段。

## 任务 2：路径构建

**文件**
- 创建：`src/codesentry/rag/path_build.py`
- 测试：`tests/test_path_build.py`

**接口**
```python
def build_paths(scan_id: int, project: str, build_id: int,
                hints: list[dict], *, depth=8, max_paths=2000,
                min_score=0.2) -> dict
```
- [ ] 种子：sink 节点、source 节点、endpoint 节点、hint。
- [ ] 反向 BFS（`calls`/`taints_to`/`contains`）与正向 BFS；交集路径。
- [ ] feasibility：`proven/likely/weak`；评分公式。
- [ ] 去重与每 (entry,sink) 最多 3 条。
- [ ] 写 `audit_paths`（pending）。
- [ ] 测试：合成图 3 条路径；重复构建幂等；无路径时不写。

## 任务 3：路径存储与认领

**文件**
- 创建：`src/codesentry/control/audit_paths.py`
- 测试：`tests/test_audit_paths.py`

**接口**
```python
claim_paths(scan_id, limit) -> list[dict]     # SKIP LOCKED
finish_path(path_id, status, result)
list_paths(scan_id, status=None, round=None, limit=100)
coverage(scan_id) -> dict
reclaim_expired(scan_id, lease_s)
enqueue_paths(scan_id, paths, round)
```
- [ ] 认领/回收/幂等 upsert。
- [ ] 测试：并发认领不重复；过期回收。

## 任务 4：单路径审计 Agent

**文件**
- 创建：`src/codesentry/agents/path_audit.py`
- 测试：`tests/test_path_audit.py`

**接口**
```python
run_path_audit(state, path: dict, runtime=None, llm=None) -> dict
```
- [ ] 构造路径上下文：节点序列、edges、入口权限、source 可控性、引擎 hint、RAG。
- [ ] 调 `run_tool_loop`（工具：graph_node/read_source/kb_search/vuln_cases/audit_patterns）。
- [ ] 解析 `verdict/confidence/cwe/severity/evidence/fix_advice`。
- [ ] 无 LLM 时按 feasibility=proven 且 taint 边 → `need_more`，否则 `clean`。
- [ ] 测试：fake LLM 返回 finding；无 LLM 保守输出。

## 任务 5：LangGraph 多轮编排

**文件**
- 修改：`src/codesentry/orchestrator/graph.py`
- 修改：`src/codesentry/orchestrator/registry.py`
- 修改：`src/codesentry/orchestrator/runner.py`
- 测试：`tests/test_path_graph.py`

**节点与边（精确）**
- `path_build`：调用 `build_paths`，返回 `coverage`。
- `audit_plan`：`claim_paths(scan_id, batch)`，把 claimed 路径放入 `audit_paths`；无路径返回 `audit_paths=[]`。
- `route_audit`（conditional）：若 `audit_paths` 非空，返回 `[Send("audit_path", {"path": p}) for p in ...]`；否则返回 `"audit_finalize"`。
- `audit_path`：调 `run_path_audit`；写 `finish_path`；返回 `path_results=[result]`、`candidate_findings` 追加（用 `Annotated` reducer）。
- `audit_collect`：生成扩展路径并 `enqueue_paths`；`audit_round += 1`；返回新 `audit_paths=[]`（清空本批）。
- `route_after_collect`：若还有 pending 且 round < max 且预算未 breach → `"audit_plan"`；否则 `"audit_finalize"`。
- `audit_finalize`：从 DB 读取 finding 结果，汇总 `candidate_findings`；进入 triage。

**State reducer**
```python
path_results: Annotated[list[dict], operator.add]
candidate_findings: Annotated[list[dict], operator.add]
```
`audit_plan` 每次必须覆盖 `audit_paths`（普通字段，不加 reducer）。

**约束**
- Send 只在 `route_audit` 中产生；不要在普通节点里返回 Send。
- `audit_path` 内不依赖其他路径；只读自己路径 + 图/源码。
- `audit_collect` 必须幂等：重复执行不重复入队（path_key 唯一）。
- 预算 breach 时 `route_after_collect` 直接 finalize，不再扩展。

- [ ] 拓扑与条件边。
- [ ] 测试：fake agent 多轮扩展；预算 breach 停止；中断后续跑。
- [ ] 测试：Send 并行 4 条路径，`path_results` 合并 4 条。

## 任务 6：Triage / Deploy / PoC 路径绑定

**文件**
- 修改：`src/codesentry/agents/triage.py`
- 修改：`src/codesentry/agents/poc_gen.py`
- 修改：`src/codesentry/agents/deploy_agent.py`
- 测试：`tests/test_path_poc.py`

- [ ] candidate/finding 增加 `path_id`、`path_nodes`、`entry`、`source`。
- [ ] Triage 输出保留 path_id。
- [ ] PoC 按路径生成：入口 URL/参数 → 路径 → sink；记录 path_id。
- [ ] 部署失败时路径 PoC verdict=`plausible`，写原因。
- [ ] 测试：路径 PoC 含 canary；无 target 降级。

## 任务 7：API 与 UI

**文件**
- 修改：`src/codesentry/web/graph_api.py` 或新建 `path_api.py`
- 修改：`web/frontend/src/views/ScanDetailView.vue`
- 创建：`web/frontend/src/components/PathAuditPanel.vue`
- 测试：`tests/test_control_api.py`

- [ ] `GET /api/scans/{id}/paths`、`/paths/{path_id}`、`/coverage`。
- [ ] ScanDetail 新 tab「审计路径」：覆盖率、路径表、状态、轮次、finding。
- [ ] 点击路径 → 图视图 `?path_id=` 高亮。
- [ ] 测试：API 形状；前端 build。

## 任务 8：真实 Agent 多轮测试

**文件**
- 修改：`tests/test_live_agents.py`

- [ ] 合成仓库：路径≥3，audit 多轮，至少 1 finding。
- [ ] OpenCode Go：Audit/Triage/Deploy 三轮 + 路径审计。
- [ ] kvf-admin：路径>10、轮次≥2、候选≥3。
- [ ] 记录 `llm_calls`/`audit_paths`/`audit_rounds` 证据。

## 任务 9：收尾

- [ ] 全量 pytest、ruff、mypy、前端 build。
- [ ] 两轮编码 review（正确性/安全/性能）。
- [ ] 更新 `doc/2026-10-24-path-centric-audit-implementation.md` 与架构文档。

## 审查重点

1. 路径认领并发安全（SKIP LOCKED / lease）。
2. 路径扩展是否去重，是否会无限增长。
3. 单路径上下文是否超预算；截断是否丢关键 sink。
4. 无 LLM/部署失败时是否降级而非崩溃。
5. 路径/hint 是否被误当成 finding（必须经审计/Triage）。
