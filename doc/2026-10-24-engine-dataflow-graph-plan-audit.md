# 引擎 Dataflow 入图 · Plan 审计

- 对象：`doc/2026-10-24-engine-dataflow-graph-plan.md`
- 结论：**通过（5 项内联修复，3 项实现注意）**

## 已修复

| # | 问题 | 修复 |
|---|---|---|
| 1 | Joern CPG 路径当前未暴露 | Task 2 明确修改 `engines/joern.py` 暴露 `cpg_out` |
| 2 | `apply_engine_graph` 节点解析可能创建重复 file/sink | 统一 key 规则，upsert + 唯一约束 |
| 3 | SARIF 多个 threadFlows 可能重复边 | `(src,dst,kind)` 唯一 + 去重 |
| 4 | 部署 `pull=never` 仍需 `local_images` 检测 | `choose_java_image` 先查本地，再决定是否 remote |
| 5 | 测试缺 dataflow 路径断言 | Task 5 增加 proven 断言 |

## 实现注意

1. Joern 查询 DSL 版本差异大：先实现“calls only”最小可用版，`reachableBy` 失败只降级；不要把整个 scan 拖死。
2. CodeQL SARIF URI 可能含 `file://`、`%20`、绝对路径；必须 normalize 后再匹配 graph path。
3. 引擎边必须保留 evidence（file:line），否则节点映射错误无法复核。

## 风险

- kvf 的 Joern CPG 可能不含跨过程 dataflow；覆盖提升以实际边数为准，不虚报。
- 边太多导致图写入慢：20k 上限 + 批量 executemany。
- 部署镜像配置错误：启动时校验，日志打印选择结果。

## 验收映射

- Task 1/2/3 单测覆盖解析与幂等。
- Task 5 单测覆盖 dataflow 路径。
- Task 6 单测覆盖镜像选择。
- Task 7 真实 kvf 记录前后覆盖数字。
