# 路径中心审计 · 实现计划审计

- 审计对象：`doc/2026-10-24-path-centric-audit-plan.md`
- 日期：2026-10-24
- 结论：**通过（6 项已内联修复，4 项实现时注意）**

## 已修复

| # | 问题 | 修复 |
|---|---|---|
| 1 | Task 5 把 Send 写在普通节点里，LangGraph 不合法 | 明确 `audit_plan` 取数、`route_audit` 条件边返回 Send、`audit_path` 执行、`audit_collect` 汇总 |
| 2 | `path_results` 多路并行需要 reducer | 明确 `Annotated[list, operator.add]`；`audit_paths` 不加 reducer |
| 3 | 多轮停止条件不清晰 | `route_after_collect`：pending + round<max + 预算未 breach |
| 4 | `audit_collect` 重复执行可能重复入队 | path_key 唯一 + 幂等 enqueue |
| 5 | 预算 breach 后仍可能扩展 | 条件边直接 finalize |
| 6 | 测试缺少并行合并断言 | 增加 4 路 Send 合并测试 |

## 实现时注意

1. **candidate_findings reducer**：`audit_path` 返回的 finding 与 `audit_finalize` 从 DB 汇总可能重复；finalize 需按 `(path_id, rule_id, file, line)` 去重。
2. **Triage 输入**：只吃 `candidate_findings`，且必须带 `path_id`；Triage 输出保留 path_id，报告与 PoC 才能回溯。
3. **部署失败**：`poc_paths` 在 `deploy_status != ready` 时仍生成 PoC，但 verdict 固定 `plausible`，execution_log 写原因。
4. **路径 PoC**：HTTP 类用入口 URL + 路径参数；本地类用 source/sink 调用样例；canary 占位符必须保留。

## 风险

- 路径扩展可能爆炸：靠 MAX_PATHS、每 (entry,sink) 3 条、round 上限、预算四重限制。
- Send 并发下 DB 连接池压力：batch ≤8，audit_concurrency ≤4。
- 跨函数参数流仍是启发式：feasibility 标注 + Agent 读源码确认。

## 验收映射

- 每条计划任务都有测试或可查询证据（audit_paths/audit_rounds/llm_calls）。
- OpenCode Go 多轮：Audit/Triage/Deploy 已单轮通过；路径审计按本计划实现后补跑。
