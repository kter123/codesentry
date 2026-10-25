# CodeSentry 剩余需求清单（2026-10-25）

> 基线：`doc/2026-10-24-requirements-core.md`、路径中心审计、CodeQL P1/P2 已完成并推送（`4320dc3`）。

## P0（完成“可落地”必须做）

| # | 需求 | 现状 | 验收 |
|---|---|---|---|
| 1 | CodeQL OSS 全链路 | 引擎/API/UI 已完成；尚未跑“扫描→CodeQL→图→路径→Triage→Deploy→PoC→报告”完整链路 | 合成 Java 仓库 oss=true 全链路通过；SARIF、codeql dataflow、finding 可见 |
| 2 | 路径级 PoC 实证 | Path finding 带 path_id；PoC 仍按 finding 生成，未验证“路径→入口 URL→canary” | 至少 1 条 path 生成可执行 PoC 并 canary 命中/明确失败原因 |
| 3 | 路径 UI 与图联动 | 路径 tab 已有；点击路径未跳转/高亮图 | 点击路径 → `/scans/:id/graph?path_id=` 高亮节点/边 |
| 4 | DeployAgent 成功部署 kvf | 本机已有 `maven:3.8-openjdk-8`；上次仍因外部镜像 403 disabled | 使用本地镜像构建/启动成功，或明确记录不可部署原因 |
| 5 | 路径审计成本收敛 | 189 条路径、batch/round 限流；entry-only 95 条可能过多 | 单次扫描在预算内完成；proven 优先；entry-only 有上限/采样 |
| 6 | 多语言引擎图 | Joern dataflow 仅 Java；CodeQL 支持多语言但需验证 | Python/JS 至少一条 dataflow/调用边真实入图 |
| 7 | 浏览器级验证 | 只做 HTTP/API 冒烟；Playwright Chromium 下载失败 | 16 路由真实渲染无白屏/控制台错误（或提供可用的本机 Chrome 方案） |
| 8 | 审计稳定性回归 | `eval_path_audit.py` 合成路径 3/3 一致；未纳入 CI | 路径级回归样例纳入测试/脚本，固定模型/温度 |

## P1（生产化增强）

| # | 需求 | 说明 |
|---|---|---|
| 9 | 路径统计 UI | coverage 已有 round/batch，页面只展示部分；补 batch、pending、dataflow_paths |
| 10 | 路径详情 | 路径节点/边/源码切片/证据详情页或抽屉 |
| 11 | 通知渠道 | 现有 webhook；补邮件/飞书/钉钉/企业微信（需求 P2，可按优先级） |
| 12 | 项目/定时扫描 | projects、scan_schedules、任务模板；当前只有单次 scan |
| 13 | 自定义 Agent | 自定义 Agent 定义/版本化；当前内置 7 个 |
| 14 | Agent 试跑对比 | dry-run/preview 已有；缺并排对比工作台 |
| 15 | 配置导入导出 | 脱敏配置包导出/导入 |
| 16 | 报告路径可视化 | 报告附路径节点/边图；当前有文字证据 |
| 17 | 大图 package 折叠 | 当前 800 节点 canvas；>2000 节点需按包聚合 |
| 18 | 磁盘/容器生命周期 | retention 已有；补定时清理与 CodeQL DB 缓存清理 |
| 19 | Python SDK/API 补全 | 已有基础 SDK；补 paths/coverage/engine status |

## P2（明确不做/暂缓）

- 多租户、部门隔离（需求方明确不做）。
- 远程 PoC target。
- 交互式 shell / 反弹 shell。
- CodeQL 自动下载/更新 packs。
- 自动修复补丁、IDE 插件、DAST/容器/IaC 扫描。

## 已知问题/技术债

1. kvf sink 覆盖 27/112：多数 sink 在静态 JS/ueditor，不在 controller 可达链；不是图写入缺陷。
2. Joern `reachableBy` 查询依赖 CPG 版本；失败只降级为 calls。
3. CodeQL `build-mode=none` 缺依赖信息；Java 复杂项目建议 manual/autobuild。
4. `audit_rounds` 已拆 batch/round，但 UI/报告统计口径需补齐。
5. `work/` 目录、Docker 镜像（9.4GB）未做周期性清理。
6. 外部 registry 不可达；本地 Java 镜像可用，长期需配置镜像源。
7. 历史 OpenCode key 未在仓库中发现；仍建议外部轮换。

## 建议执行顺序

1. P0-1 CodeQL 全链路验证
2. P0-2 路径级 PoC
3. P0-4 kvf 本地镜像部署
4. P0-3 路径 UI 联动 + P1-9/10 路径详情
5. P0-5 成本收敛
6. P0-6 多语言图
7. P0-7 浏览器验证
8. P0-8 回归
9. P1 生产化增强
