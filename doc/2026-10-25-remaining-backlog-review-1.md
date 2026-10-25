# 剩余需求 Code Review 第 1 轮（正确性/收敛）

- 日期：2026-10-25
- 范围：`git diff`（路径队列、CodeQL、PoC、部署、API、前端）与实跑结果

| # | 等级 | 问题 | 修复 |
|---|---|---|---|
| 1 | 必须 | `need_more` 写回 `pending` 后被反复认领，导致递归 200/600/1000 爆栈 | `claim_paths` 增 `attempts < max_attempts`；默认 2；实测 Java 全链完成 |
| 2 | 必须 | pending 路径每轮扩兄弟路径，成本指数增长 | 仅 `finding` 或首轮 `proven` 扩展；其余不再扩 |
| 3 | 必须 | CodeQL SARIF 无 `level`，CWE 在 `tags`，原解析得到 medium/610 | 读取 `problem.severity`，从 tags 正则提取 `cwe-078`；实测 high/78 |
| 4 | 必须 | 同函数 source→sink 解析为同一节点，dataflow 自环被 `apply_engine_graph` 丢弃 | 解析到真实 sink 节点（按 path/line），无则建 sink 占位；实测 dataflow=1 |
| 5 | 必须 | 无 LLM 时路径候选 CWE 610 覆盖 CodeQL hint 78 | `_merge_hints` 按 file:line 合并 hint 的 CWE/severity/message，保留 path_id |
| 6 | 重要 | 路径统计 `pending` 始终为 1/0，UI 不真实 | collect 每次查 `coverage`，返回真实 pending/batch/dataflow |
| 7 | 重要 | `coverage` 缺 sinks_total，无法判断覆盖 | 从 scans.repo_path + graph_nodes 统计 |
| 8 | 重要 | Graph API `focus` 可能被 limit 截掉 | focus 节点优先查询并置顶 |
| 9 | 重要 | maven 镜像内 `java` 不在 PATH，kvf 启动 `exec: java: not found` | 依次尝试 `$JAVA_HOME/bin/java`、`java`、`/usr/lib/jvm/*/bin/java`、`/opt/java/openjdk/bin/java` |
| 10 | 重要 | 路径 PoC 无 target_url 时会臆造入口 host | 仅部署 ready 且有 target_url 时拼 `full_url`；否则只给 route |
| 11 | 建议 | 报告无引擎/CodeQL 信息，验证脚本只能看 DB | 报告增加“引擎与图增量”段 |
| 12 | 建议 | 路径详情 API 只返回原始 key，UI 无法展示名称/位置 | 增 `nodes_detail/edges_detail` |

## 实跑复核

- Java：`done`，`path.78` high，CWE-78，2 条 proven 路径。
- Python：`done`，4 条 proven 路径。
- JS：`done`，dataflow=1，2 条 CodeQL findings；路径为 weak（file 级 source）。
- kvf：`degraded`，构建/启动成功，MySQL `Connection refused`。
- UI：21/21 路由 + 路径抽屉通过。

## 结论

正确性阻断项已修复；剩余 JS 匿名回调节点问题记录为已知限制，不影响 CodeQL 结果与图 dataflow。
