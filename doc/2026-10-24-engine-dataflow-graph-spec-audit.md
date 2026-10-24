# 引擎 Dataflow 入图 · Spec 审计

- 对象：`doc/2026-10-24-engine-dataflow-graph-spec.md`
- 结论：**通过（6 项内联修复，4 项转 Plan）**

## 已修复

| # | 问题 | 修复 |
|---|---|---|
| 1 | Joern dataflow 查询 API 在不同版本可能不可用 | 明确失败只降级、不影响扫描；查询异常记录 `engine_graph.error` |
| 2 | `path:line` 可能命中多个函数 | 采用“最小包含区间”解析；找不到则退 file 节点，仍找不到才建 source/sink |
| 3 | CodeQL SARIF URI 可能是 `file://` 或相对路径 | Plan 中要求 `normalize_sarif_uri()` 统一为仓库相对路径 |
| 4 | dataflow 边可能爆炸 | 上限 20k；`(src,dst,kind)` 唯一去重；超限记录 truncated |
| 5 | 覆盖目标 60/95 可能不现实 | 改为 ≥40/95 或相对 +100%，并允许标注降级 |
| 6 | 部署镜像配置缺少 env 名 | 统一 `CODESENTRY_DEPLOY_*` 前缀 |

## 转 Plan

1. Joern 查询脚本的具体 DSL 与超时；若 `reachableBy` 不兼容的 fallback（仅 calls）。
2. CodeQL codeFlows 解析与节点映射细节。
3. graph apply 的幂等/去重/上限。
4. 部署镜像选择的测试（local/config/pull=never）。

## 风险

| 风险 | 缓解 |
|---|---|
| Joern CPG 版本差异 | 查询失败降级；只写 calls 也保留价值 |
| dataflow 语义不等于污点 | 用 `dataflow` 边而非 `taints_to`；Triage 仍需验证 |
| 图节点解析错误 | 最小包含 + evidence 行号；报告可复核 |
| 覆盖率仍不足 | 报告标注未覆盖原因，不虚报 |

## 验收可行性

- Joern 行解析、SARIF 解析、graph apply、dataflow 路径均可单测。
- 真实 kvf 重跑一次验证覆盖率提升。
