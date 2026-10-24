# 路径中心多轮审计 · 实现记录

- 日期：2026-10-24
- 规格：`doc/2026-10-24-path-centric-audit-spec.md`
- 计划：`doc/2026-10-24-path-centric-audit-plan.md`
- 审计：spec/plan 审计文档同名 `-audit`

## 已实现

| 能力 | 文件 |
|---|---|
| 审计路径表 / 轮次表 | `db/ddl.py`：`audit_paths`、`audit_rounds` |
| 路径构建（sink 反向 BFS + 评分 + 可行性 + 文件级兜底） | `rag/path_build.py` |
| 路径队列（SKIP LOCKED 认领、lease 回收、扩展） | `control/audit_paths.py` |
| 单路径审计 Agent | `agents/path_audit.py` |
| LangGraph 多轮节点（path_build / audit_plan / audit_path Send / audit_collect / audit_finalize） | `agents/path_audit_nodes.py`、`orchestrator/graph.py` |
| 路径 API | `web/graph_api.py`：`/paths`、`/paths/{id}`、`/coverage` |
| UI | `ScanDetailView` 新增「审计路径」tab |
| 真实 Agent 测试 | `tests/test_live_agents.py` 4 轮 |

## 行为

1. `scan` 产出 `engine_hints`，并写入图 sink。
2. `path_build` 从 sink 反向 BFS 到 endpoint/route，生成 `proven/likely/weak` 路径；同文件入口补充 weak 路径。
3. `audit_plan` 用 `FOR UPDATE SKIP LOCKED` 认领一批路径。
4. `route_audit` 用 LangGraph `Send` 并行审计；单路径 Agent 读代码切片 + 图 + RAG，输出 finding/clean/blocked/need_more。
5. `audit_collect` 写轮次统计、同函数兄弟 sink 扩展。
6. 达到轮次上限/预算后 `audit_finalize` 汇总 finding 与高可行 pending 为候选，进入 Triage。
7. Triage → DeployAgent → PoC → Report。

## 防卡死

- 单路径 Agent 在 daemon 线程中执行，60s 超时后返回 `need_more`，不阻塞扫描。
- 每条路径独立 LLM session，避免网关按 session 串行。
- `audit_path` 并行分支不写 `budget/phase`，避免 LangGraph 并发更新冲突。

## 验证结果（2026-10-24）

- 全量测试：`293 passed, 2 skipped, 6 deselected, 1 xfailed`；ruff/mypy 全绿。
- OpenCode Go 真实 Agent 4 轮全部通过：
  - AuditAgent 产出候选（含 file/line/证据/修复建议）；
  - TriageAgent 图路径判定（keep，confidence 0.62）；
  - DeployAgent 构建 nginx 镜像并启动，`status=ready`、`target_url` 非空；
  - 单路径 AuditAgent 判定 `finding`（confidence 0.97）。
- kvf-admin 路径审计：
  - run 1164：37 条路径、20 个入口、7 个 sink、6 轮、**10 条 finding**（因 recursion_limit=30 在 finalize 前失败，已修复为 200）；
  - run 1212：3 轮、**4 条 finding**、3 条 clean、8 条 pending；
  - run 1214：完整链路 `path_build → audit(2 轮) → triage → deploy → poc → report` 全部节点结束；
    - 路径 19 条、入口覆盖 6、sink 覆盖 7；3 clean、16 pending；
    - DeployAgent 实际尝试构建（388s，12.8k tokens），因外部镜像仓库 `openjdk:8-jre` 返回 403 最终 `disabled`，原因已落库；
    - 本次审计结论为 0 finding（LLM 判定路径 clean）。

## 结论

路径中心多轮审计、Agent 主导部署、Prompt 可配置、引擎转图、RAG 工具化均已落地。剩余为覆盖率提升与部署镜像源问题，不是链路阻塞。

## 后续问题的处理（2026-10-24）

| 问题 | 处理 | 结果 |
|---|---|---|
| Java 镜像 403 | DeployAgent 增加 `local_images`/`java_images` 工具；确定性 maven 配方自动选本机 Java/Maven 镜像 | 识别并使用 `docker.m.daocloud.io/library/maven:3.8-openjdk-8`，不再写不可达的 `openjdk:8-jre` |
| 路径覆盖 20/95 | 增加同目录 `entry_package` 与同模块 `entry_module` 弱路径 | kvf：路径 43→81，sink 覆盖 7→26 |
| 审计结论波动 | Prompt 明确 proven+taint 不得判 clean；proven clean 强制 `need_more`；新增 `scripts/eval_path_audit.py` | 合成路径 3 轮全部 finding，consistency=1.0 |
| batch/round 混用 | state 新增 `audit_batch`；`audit_round` 只在产生扩展路径时推进；coverage 同时输出 round/batch | 批次与扩展轮次分离 |

## 测试

- `tests/test_path_audit.py`：路径构建、队列认领、单路径审计解析、Send 路由。
- `tests/test_path_graph.py`：LangGraph 多轮 + 候选汇总。
- `tests/test_live_agents.py`：
  - Round 1 AuditAgent（OpenCode Go）产出候选；
  - Round 2 TriageAgent 图路径判定；
  - Round 3 DeployAgent 构建/启动 `ready`；
  - Round 4 单路径审计 finding。

## 后续

- 路径覆盖率继续提升：当前 kvf 20/95 入口、26/112 sink；需补引擎 dataflow 边与跨包调用解析。
- 部署：本机 Java 镜像已可用；外部 registry 仍不可达，建议长期配置本地镜像源。
- 前端可按 package 聚合大图；当前 canvas + 800 节点已不卡顿。
