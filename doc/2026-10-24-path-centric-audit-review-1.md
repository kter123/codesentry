# 路径中心审计 · 代码 Review 第 1 轮（正确性/并发）

- 范围：`rag/path_build.py`、`control/audit_paths.py`、`agents/path_audit.py`、`agents/path_audit_nodes.py`、`orchestrator/graph.py`
- 日期：2026-10-24

## 发现与修复

| # | 等级 | 问题 | 修复 |
|---|---|---|---|
| 1 | 必须 | `audit_path` Send 分支返回 `phase`，并行写同名 key 导致 `INVALID_CONCURRENT_GRAPH_UPDATE` | 移除 `phase` 返回；只返回 `path_results` |
| 2 | 必须 | `_wrap` 对所有节点写 `budget`，并行分支冲突 | `audit_path` 不写 `budget`，由 collect/后续节点写 |
| 3 | 必须 | `audit_path` 用 `_wrap("audit")`，被当作普通 audit 节点，无法跳过 budget | `_wrap` 增加 `cfg_name` 映射；节点名为 `audit_path`，配置/提示词仍用 `audit` |
| 4 | 必须 | `route_after_collect` 在 DB 查询 pending 时可能阻塞 | 改为按 `audit_round` 与预算路由；批次排空由 `audit_plan` 认领为空后进入 triage |
| 5 | 必须 | triage 回边返回 `"audit"`，但图里没有该节点（只有 `audit_plan`） | `_route_triage` 将 `audit` 映射为后续部署；路径审计已多轮，不再回环 |
| 6 | 必须 | `path_build` 中 `nodes` 变量被路径节点列表覆盖，`_coverage` 报 `'list' has no attribute 'values'` | 重命名为 `path_nodes` |
| 7 | 建议 | `scan_id <= 0` 的单元测试会复用历史 `audit_paths`，导致多轮空转 | `path_build/audit_plan/finalize` 对 `scan_id<=0` 直接跳过 |
| 8 | 建议 | 入口与 sink 同文件时无路径，覆盖率过低 | 增加 `entry_file` weak 路径（受 `min_score` 控制） |

## 验证

- `tests/test_path_audit.py`、`tests/test_path_graph.py` 通过。
- 全量 293 passed。
- kvf 多轮：35 路径、20 入口、6 轮、10 findings（run 1164）；4 findings（run 1212）。

## 遗留

- 每批审计的 `round` 实际是批次号；真正的“扩展轮次”需与批次解耦。
- `audit_rounds.paths_audited` 使用累计 `path_results`，统计口径需按批修正。
