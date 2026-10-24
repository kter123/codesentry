# 引擎 Dataflow 入图 · Code Review 第 1 轮（正确性）

- 范围：`engines/joern_graph.py`、`engines/codeql_graph.py`、`rag/graph_delta.py`、`rag/path_build.py`、`agents/scan.py`

## 发现与修复

| # | 等级 | 问题 | 修复 |
|---|---|---|---|
| 1 | 必须 | Joern `method.filename` 在 kvf CPG 返回 `k`，路径全错 | 统一改用 `file.name`；sink 查询早已如此 |
| 2 | 必须 | `JOERN_FLOW` 解析按 7 段，实际 6 段，dataflow 全丢 | 改为 6 段并修正索引 |
| 3 | 必须 | 每条 call 单独查 DB，20k 次不可接受 | 预加载 name→node_key 映射，单次查询 |
| 4 | 必须 | entry-only 路径没有 file/line，finding 无法落点 | 从 endpoint 节点反查 path/start；`_to_finding` 支持 |
| 5 | 必须 | 覆盖率把 route 入口算成 endpoint，出现 102/95 | 只统计 endpoint_key 交集 |
| 6 | 建议 | 同模块/同目录弱路径仍不足 | 增加 `entry_only` 入口审计路径，覆盖 95/95 |

## 验证

- Joern 实跑：methods 1941、calls 364、flows 38、dataflow 26。
- 路径：189 条，endpoint 95/95，sink 27/112，dataflow_paths 27。
- `tests/test_engine_graph.py` 4 passed。

## 遗留

- dataflow 边可能指向图中不存在的 file 节点（当前无 FK，路径构建会忽略）；下轮补 placeholder。
