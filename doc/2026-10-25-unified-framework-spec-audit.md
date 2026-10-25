# 统一框架 Spec 审计

- 结论：有条件通过；以下 12 项必须在 plan 落实。

## 阻断项

| # | 问题 | 修订 |
|---|---|---|
| 1 | Supervisor 与现有 `audit_plan/collect` 重复 | Supervisor 成为唯一路由；`audit_plan/collect` 降为执行器，不再决定下一跳。 |
| 2 | 一个 finding 多路径/多来源可能重复 | 统一 key `scan_id+path_id`；无 path_id 的引擎候选使用 `scan_id+rule+file+line`。 |
| 3 | 事件 seq 并发重复 | `agent_events(scan_id,seq)` 唯一 + advisory lock；插入冲突重试。 |
| 4 | stop 不能中断正在跑的 LLM | 节点边界检查 + 当前节点超时；stop 后不再认领新路径。 |
| 5 | Harness 结果不能覆盖人工/Triage 结论 | Harness 只写 `verification_runs` 和 `verdict`，Triage 可覆盖并记录来源。 |
| 6 | 工具结果直接进报告的风险 | 工具只写 evidence/tool_runs；必须经 path/triage 才能成为 finding。 |
| 7 | 工作台一次加载全部事件会卡 | SSE 增量 + 最多 1000 条 + 过滤 + 虚拟滚动。 |
| 8 | 即时分析执行用户代码 | 只写临时仓库并走正常扫描，不执行用户代码。 |
| 9 | 证据包泄露 | 排除密钥/源码全文，只打包摘要、finding、verification、events。 |
| 10 | 全语言 Harness 镜像缺失时伪报 | 运行时不满足 → `environment_error`/`plausible`。 |

## 重要项

| # | 问题 | 修订 |
|---|---|---|
| 11 | 知识包与 kb_chunks 重复 | 知识包独立表；可选同步 kb_chunks，source 带 `pack:` 前缀。 |
| 12 | 前端做 React 微前端 | 统一 Vue3，不引入第二套前端运行时。 |

## 结论

按此进入 plan；先完成 Supervisor/事件/控制/工作台，再 Harness/工具/知识/产品化。
