# A3/A4 + B1/B2 实现计划

**目标：** 让多 Agent 分析过程可见，并让上传的 Web 包在 Docker 中真实部署、支持 PoC 实证。

**架构：** 节点产物 + 工具轨迹 + WS 事件；DockerDeployer 默认 host 模式部署，优先 Dockerfile，扫描结束清理；CanaryVerifier 由 PoC 自身占位符产生证据。

**规格：** `doc/2026-10-22-agent-flow-poc-verification-spec.md`（审计：`...-spec-audit.md`）

## 全局约束

- 部署与 PoC 执行解耦：`DEPLOY_ENABLED` 控制部署，`POC_RUN` 控制 PoC 执行。
- host 模式只绑定 127.0.0.1；internal 模式不发布端口。
- 上传源码不被修改；语言配方使用临时工作区。
- 无占位符的 PoC 不得标 `verified`。
- 真实 Docker 操作失败时降级 `disabled/degraded`，链路继续。

## 审查重点

1. 默认部署是否真的启动容器（不是 built）。
2. host 模式 target 是否可访问；internal 模式是否有内网健康检查。
3. Dockerfile 构建失败/超时是否降级并记录日志。
4. zip 嵌套根/端口探测是否正确。
5. 扫描结束是否清理容器/网络/工作区。
6. canary 是否由 PoC 自身执行，而不是直接 exec echo。
7. artifacts/WS 是否不破坏旧图/旧测试。

---

## 任务 1：部署语义与配置

- 文件：`config.py`、`sandbox/deploy.py`、`tests/test_m6_runtime.py`
- 步骤：新增 `deploy_enabled/network_mode/port/keep`；`run_deploy` 默认部署；测试 `POC_RUN=off` 仍部署、`DEPLOY_ENABLED=false` → disabled。

## 任务 2：项目根/Dockerfile/端口

- 文件：`sandbox/deploy.py`
- 步骤：`resolve_project_root` 支持嵌套；`detect_port` 读 EXPOSE/app.py；`_build_image` 构建 Dockerfile；测试嵌套根 + 端口。

## 任务 3：host/internal 与生命周期

- 文件：`sandbox/deploy.py`、`orchestrator/runner.py`
- 步骤：host 发布随机端口、internal 容器内健康；临时工作区；扫描结束 `cleanup_scan`（`DEPLOY_KEEP` 可保留）。

## 任务 4：PoC canary

- 文件：`sandbox/verify.py`、`agents/poc_gen.py`、`tests/test_m6_runtime.py`
- 步骤：PoC 占位符替换；`{CANARY_CMD}` 回显、`{CANARY_FILE}` 副作用、`{CANARY_URL}` 回调；无占位符 plausible；真实容器验证 613。

## 任务 5：工具循环与预算

- 文件：`agents/tools.py`、`agents/triage.py`、`agents/poc_gen.py`、`orchestrator/budget.py`、`orchestrator/graph.py`
- 步骤：`run_tool_loop`；`max_iterations`；`budget_override` 超限跳过；`tool_trace` 落库。

## 任务 6：Artifacts + WS + UI

- 文件：`orchestrator/artifacts.py`、`orchestrator/events.py`、`orchestrator/telemetry.py`、`web/server.py`、`web/control_api.py`、`web/graph_api.py`、`web/frontend/src/views/ScanDetailView.vue`、`web/frontend/src/api/types.ts`
- 步骤：哈希链/校验；节点事件总线；WS pump；审查链 tab、实时事件、finding 工具轨迹/置信度/验证字段。

## 任务 7：真实联调与验收

- 步骤：真实扫描 612 host 部署 ready + target 可访问 + 清理；真实 canary 613 命令回显命中；全量测试、ruff/mypy、Vue build。

## 任务 8：两轮 review 与文档

- 步骤：review 1（安全/生命周期/canary 语义）、review 2（兼容/回归/UI）；修复；更新需求与架构文档；提交。
