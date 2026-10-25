# 剩余需求实现记录（P0 + P1）

- 日期：2026-10-25
- 规格：`doc/2026-10-25-remaining-backlog-spec.md`（含审计修订）
- 计划：`doc/2026-10-25-remaining-backlog-plan.md`
- 基线：`4320dc3`

## 交付摘要

| 需求 | 状态 | 实现要点 |
|---|---|---|
| P0-1 CodeQL 全链路 | ✅ | 多语言 CodeQL spec、SARIF URI 归一、CWE tags、severity 回退、codeFlows→sink dataflow、Java/Python/JS 实跑 |
| P0-2 路径级 PoC | ✅ | `_path_context` 按 `scan_id+path_id` 读取入口/节点/边、`entry_url`、`{CANARY_URL}` 保留、结果写 `path_id/entry_url` |
| P0-3 路径 UI/图联动 | ✅ | 路径统计 tags、路径抽屉（节点/边/证据/源码）、`?path_id=` 高亮、focus 参数保证路径节点入图 |
| P0-4 kvf 部署 | ✅（degraded） | 本地 `maven:3.8-openjdk-8` 构建成功；Java 路径 fallback；MySQL/Redis 缺失 → degraded + 明确日志 |
| P0-5 成本收敛 | ✅ | `audit_max_paths=240`、`entry_only_max=48`、`attempts_max=2`、proven 优先、单路径超时配置 |
| P0-6 多语言图 | ✅ | 每语言 CodeQL；`javascript/typescript` 去重；Python/JS dataflow 入图 |
| P0-7 浏览器验证 | ✅ | Playwright Chromium：**21/21** 路由通过（含路径抽屉）；Safari WebDriver 环境 BLOCKED 保留 fallback |
| P0-8 审计回归 | ✅ | `tests/fixtures/path_eval.json` 3 例；`eval_path_audit.py --dataset`；离线回归测试 |
| P1-9/10 路径统计/详情 | ✅ | `coverage` 扩展 total/pending/entry_only/dataflow/sinks_total/batch；路径节点/边解析 |
| P1-11 通知渠道 | ✅ | generic/feishu/dingtalk/wecom/email；secret 加密；headers 脱敏；SMTP 配置/测试 |
| P1-12 项目/定时 | ✅ | projects/scan_schedules、5 段 cron、原子认领、运行/启停/删除 UI |
| P1-13 自定义 Agent | ✅ | agent_presets、绑定到内置节点、invariant tail 强制保留、工具/技能/能力合并 |
| P1-14 试跑对比 | ✅ | `/api/agents/{name}/compare`；默认 dry-run，真实 LLM 显式开关 |
| P1-15 配置导入导出 | ✅ | 导出排除 key/secret/codeql_build_command；merge/replace upsert；UI 下载/导入 |
| P1-16 报告路径图 | ✅ | 报告“攻击路径”表 + Mermaid；SARIF properties `path_id`；报告附引擎/图增量 |
| P1-17 图包聚合 | ✅ | `按包聚合`、包节点计数、点击包展开 |
| P1-18 生命周期 | ✅ | purge 补 audit_paths/audit_rounds 等；CodeQL cache/orphan workdir/target image；维护 API/UI |
| P1-19 SDK | ✅ | list_paths/get_path/coverage/codeql_status/engine_test/export/import |

## 关键代码

- 路径队列/成本：`control/audit_paths.py`、`agents/path_audit_nodes.py`、`agents/path_audit.py`、`config.py`
- CodeQL：`engines/codeql.py`、`engines/codeql_graph.py`、`agents/scan.py`、`scan_orchestrator.py`
- 路径 PoC：`agents/poc_gen.py`、`sandbox/verify.py`
- 图/路径 UI：`web/graph_api.py`、`GraphView.vue`、`ScanDetailView.vue`
- 部署：`sandbox/deploy.py`
- 通知：`control/webhooks.py`、`control/notifications.py`
- 项目/调度：`control/projects.py`、`control/scheduler.py`、`web/projects_api.py`、`ProjectsView.vue`
- Agent Preset/对比：`control/agent_presets.py`、`agents/runtime.py`、`control_api.py`、`AgentDetailView.vue`
- 配置/生命周期/SDK：`control/config_io.py`、`control/retention.py`、`sdk.py`
- 报告：`agents/report.py`、`reportex/sarif.py`

## 真实验证

### CodeQL 全链路

| 语言 | CodeQL | dataflow | 路径 | 结果 |
|---|---|---|---|---|
| Java | ok | 1 | 2 proven | `path.78` high；CWE-78；报告生成 |
| Python | ok | ≥1 | 4 proven | command injection 路径；报告生成 |
| JavaScript | ok | 1 | 0 proven（file 级 source） | 2 条 CodeQL findings（CWE-78/770） |

- 修复点：SARIF `tags=["external/cwe/cwe-078"]` 提取 CWE；无 `level` 时用 `problem.severity`；同函数 source→sink 不再因自环被丢弃，dataflow 指向真实 sink 节点。
- 扫描完成状态：Java/Python/JS 均 `done`，报告存在。中途修复了 `need_more` 状态被反复认领导致的 recursion 爆栈（attempts 上限 + 首轮扩展策略）。

### kvf 部署

- 源码：`work/3650f1b569/src/kvf-admin-master`
- 镜像：`docker.m.daocloud.io/library/maven:3.8-openjdk-8`（本地，`pull=never`）
- 结果：`degraded`，target `http://127.0.0.1:<随机端口>/`
- 原因：容器日志 `Communications link failure / Connection refused`，MySQL 未就绪；同时检测到 Redis 依赖。
- 说明：Jar 构建成功并启动到 Spring 初始化阶段；不是镜像/构建失败。

### 浏览器

- `web/frontend/scripts/ui_smoke.mjs`（Playwright Chromium）
- 覆盖：概览、扫描、项目、复核、Agent 列表/详情、LLM、用量、Prompt、Skills、KB、规则、编排、审计、设置、用户、登录、扫描详情、代码图、路径图高亮、路径抽屉
- 结果：`passed=21, total=21`，无 console error。
- Safari WebDriver：`BLOCKED: timed out`（未启用远程自动化），保留 `scripts/ui_smoke_safari.py` 作为 fallback。

### 回归

```
352 passed, 2 skipped, 6 deselected, 1 xfailed
ruff: All checks passed
mypy: Success: no issues found in 111 source files
frontend: npm run build 通过
```

## 已知限制

1. JavaScript 的 CodeQL source 落在箭头回调内时，tree-sitter 只解析到 `file:` 节点，路径为 weak；CodeQL finding 仍保留在 fallback 候选中。后续可将匿名回调提升为 function 节点。
2. kvf 需要 MySQL/Redis；没有依赖编排时只能 `degraded`，不会伪报 ready。
3. Safari 自动化环境未开启；Playwright 已覆盖浏览器验证。
4. 配置导出不包含密钥；导入到新环境后需重新填写 LLM/SMTP secret。
5. `run_audit_finalize` 保留为无 AuditAgent 时的兜底；默认链路仍由 AuditAgent 合并路径候选与引擎 hint。
