# 路径中心审计 · Spec 审计

- 审计对象：`doc/2026-10-24-path-centric-audit-spec.md`
- 日期：2026-10-24
- 结论：**通过（8 项已内联修复，5 项转入 Plan）**

## 一、已修复

| # | 等级 | 问题 | 修复 |
|---|---|---|---|
| 1 | 必须 | `calls` 边不等于参数可控流到 sink | 新增 §4.5 `proven/likely/weak` 可行性分级与评分系数 |
| 2 | 必须 | 图不完整时路径缺失，会把“未解析”误判不可达 | 新增 §4.6 文件级/启发式兜底，报告展示 unresolved |
| 3 | 必须 | 并发 Send 可能重复审计同一路径 | §5.3 `FOR UPDATE SKIP LOCKED` 认领 + lease 回收 |
| 4 | 必须 | 长任务中断后无法续跑 | §5.3 幂等 upsert + pending 续跑，验收补充 |
| 5 | 建议 | 单路径源码上下文可能撑爆 | §5.4 24KB/节点 120 行预算 |
| 6 | 建议 | UI/API 缺少路径查询 | §8.1 路径列表/详情/覆盖率 API |
| 7 | 建议 | kvf 验收强制 finding ≥3 不现实（可能全是误报） | 改为候选 ≥3，允许 Triage demote/reject |
| 8 | 建议 | 实时事件缺少路径粒度 | §8.2 增加 round/path 事件 |

## 二、转入 Plan

1. **跨函数参数映射**：`likely` 路径的具体启发式（参数名/位置/顺序）与 Agent 确认步骤。
2. **LangGraph Send + reducer**：`path_results` 使用 `Annotated[list, operator.add]`；dispatch 批大小与条件边细节。
3. **路径扩展去重**：sibling/neighbor 的生成规则与上限。
4. **部署失败时的 PoC 路径**：`deploy_status != ready` 时路径 PoC 如何降级为 plausible。
5. **性能**：2000 路径的 DB/LLM 成本估算与分批策略。

## 三、风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 路径爆炸 | 成本失控 | MAX_PATHS/评分/每 entry-sink 3 条/预算 |
| 跨函数参数流误判 | 误报 | feasibility + Agent 读源码确认 + Triage |
| 图缺失 | 漏报 | 引擎 hint 文件级兜底 + 报告标注 |
| 部署失败 | PoC 无法验证 | 降级 plausible，报告写明原因 |
| 长任务 | 超时/中断 | lease、断点续跑、批次事件 |

## 四、验收可行性

- 合成仓库路径可自动化断言。
- kvf 路径数/轮次可查询 `audit_paths`。
- OpenCode Go 真实 Agent 已能跑 Audit/Triage/Deploy 单轮；多轮路径审计需 Plan 落地后重跑。
