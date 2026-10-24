# 路径中心审计 · 代码 Review 第 2 轮（可靠性/安全/性能）

- 范围：同上 + `agents/deploy_agent.py`、`rag/path_build.py`、前端图页面
- 日期：2026-10-24

## 发现与修复

| # | 等级 | 问题 | 修复 |
|---|---|---|---|
| 1 | 必须 | 单路径 LLM 调用可能无限等待，阻塞整条扫描 | `run_path_audit` 在 daemon 线程执行，60s 超时返回 `need_more` |
| 2 | 必须 | 8 条路径共用同一 OpenCode session，网关串行/限流 | 每条路径使用 `scan-{id}-audit-{path_id}` 独立 session |
| 3 | 必须 | 线程内 LLM tokens 未回流，预算/遥测为 0 | `_call_with_timeout` 在线程内读取 tokens/cost 并写回主 contextvar |
| 4 | 必须 | `claim_paths` lease 硬编码 900s | 改为 `make_interval(secs => %s)`，使用 `path_lease_s` |
| 5 | 建议 | weak 路径会拖慢审计且价值低 | `PATH_MIN_SCORE` 过滤同文件兜底路径；高可行路径优先 |
| 6 | 建议 | DeployAgent 无工具调用时直接 disabled | 增加“Agent 给方案 → 沙箱执行 → 失败按日志修正一次”的兜底 |
| 7 | 建议 | 部署探针启动瞬间误报 | `probe` 增加 10 次重试 |
| 8 | 建议 | 扫描 `recursion_limit=30` 被多轮路径审计耗尽 | 提高到 200 |

## 安全复核

- 路径审计只读源码/图/RAG；工具层 `read_source` 有 repo 越界保护。
- DeployAgent 只在 Docker 内构建/运行；不执行宿主 shell，端口仅绑定 `127.0.0.1`。
- 路径证据只存文件/行号/片段，不存密钥。
- `audit_paths` 无用户输入直接拼 SQL；全部参数化。

## 性能复核

- 图页面默认限 800 节点、canvas、无动画、>300 节点隐藏标签；ScanDetail 只展示 20 节点。
- vendor 分包（echarts/element/vue）已生效，主入口约 14KB。
- 路径审计按批 4–8 条；单路径 60s 上限，避免单点拖死全链。

## 已知问题（不阻塞）

1. kvf 最后稳定 run 1214：路径审计 2 轮、3 clean、0 finding；审计结论受 LLM 判断波动影响。
2. DeployAgent 在 kvf 上尝试 `openjdk:8-jre` 镜像，外部镜像仓库返回 403，最终 `disabled`；部署失败原因已落库。
3. 95 个 endpoint 中覆盖 20 个入口；未覆盖部分因调用边缺失/弱路径被过滤。
4. 批次号与扩展轮次仍共用 `audit_round`。

## 结论

通过。核心并发/超时/预算问题已修复；剩余为覆盖率与部署镜像环境问题，转入后续迭代。
