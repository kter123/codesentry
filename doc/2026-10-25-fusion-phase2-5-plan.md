# Fusion Phase 2–5 实施计划

**目标：** 在 Phase 1 基础上完成 Supervisor、事件流、审计工作台、全语言 Harness、工具网关、知识包和产品化。

## 任务 1：事件与扫描控制

**文件：** `db/ddl.py`、`orchestrator/events.py`、`orchestrator/telemetry.py`、`control/scan_control.py`（新）、`web/control_api.py`、`agents/path_audit_nodes.py`

- [ ] DDL：`agent_events`、`agent_nodes`、`scan_controls`。
- [ ] `events.publish_event(scan_id,event_type,agent,phase,payload)`：写 DB + 内存广播；`agent_events.seq` 每 scan 自增（事务内 `max(seq)+1`）。
- [ ] `telemetry.node_run` 自动写 `agent.start/end` 事件和 `agent_nodes`。
- [ ] `control/scan_control.py`：`request_pause/resume/stop`、`should_stop`、`wait_if_paused(max_s=300)`。
- [ ] `_wrap` 在每个节点入口调用 `wait_if_paused`，stop 抛 `ScanStopped`；runner 捕获后标记 `stopped`。
- [ ] API：pause/resume/stop/events/agent-tree；SSE `StreamingResponse` 从 DB 回放后轮询。
- [ ] 测试：事件 seq、SSE 首包、pause/stop。

## 任务 2：Supervisor 节点

**文件：** `agents/supervisor.py`（新）、`orchestrator/graph.py`、`agents/state.py`、`control_api`（查看决策）。

- [ ] Supervisor 动作白名单：`audit|triage|report|finish`；输入 coverage/budget/candidates。
- [ ] 规则：预算 breach→report；pending>0→audit；有 candidate/proven→triage；否则 finish。
- [ ] 写入 `agent_events`（`supervisor.decision`）和 `state.supervisor`。
- [ ] 图：path_build→supervisor→audit_plan/triage/report；audit_collect→supervisor。
- [ ] 测试：决策序列、预算熔断、无路径。

## 任务 3：审计工作台

**文件：** `web/frontend/src/views/WorkbenchView.vue`（新）、`router`、`AppLayout`、`ScanDetailView` 入口。

- [ ] 路由 `/scans/:id/workbench`。
- [ ] 左：agent-tree；中：事件流（SSE + 历史）；右：事件/路径/finding 上下文。
- [ ] 顶部：状态/预算/coverage/verified/plausible/rejected；暂停/恢复/停止。
- [ ] 底部 tabs：路径、Findings、验证、图、报告；复用现有 API。
- [ ] 过滤：event_type、agent、severity；自动滚动开关。
- [ ] 测试：build + Playwright 工作台。

## 任务 4：Harness 全语言与模板

**文件：** `control/harness_templates.py`（新）、`control/harness.py`、`docker/harness/Dockerfile`、`config.py`

- [ ] 模板：CWE-78/89/79/22/94/95/502/918/611/1333，语言命令矩阵。
- [ ] `generate_harness` 传入模板提示；LLM 失败可回退固定模板（仅高频简单场景）。
- [ ] `extract_function`: 基于 graph_nodes 查函数并返回源码切片；API/工具。
- [ ] 默认 `harness_image=codesentry-harness:latest`；无镜像 environment_error。
- [ ] Dockerfile 安装 Python/Node/PHP/JDK/Go/Ruby（构建可选）。
- [ ] 测试：模板选择、语言命令、extract_function。

## 任务 5：工具网关

**文件：** `control/tool_gateway.py`（新）、`web/control_api.py`、`web/frontend` 工具证据面板。

- [ ] 注册表：gitleaks/bandit/osv/npm_audit/safety；固定 argv、超时、无网络。
- [ ] 输出归一化：`{status,items,evidence,error}`。
- [ ] 工具结果写 `tool_runs`，并作为 `agent_events` 的 `tool.result`。
- [ ] API：`GET /api/scans/{id}/tools`、`POST /api/scans/{id}/tools/{tool}`。
- [ ] UI：工作台“工具证据” tab；不可用显示原因。
- [ ] 测试：mock subprocess、缺工具 unavailable、参数校验。

## 任务 6：知识包

**文件：** DDL `knowledge_packs`、`control/knowledge_packs.py`（新）、`rag/retrieve.py`、`web/control_api.py`、`KnowledgeView.vue`。

- [ ] 内置框架/漏洞包定义（clean-room 文本）。
- [ ] CRUD + 启停 + 版本；导入大小限制。
- [ ] 检索加权：语言/框架/CWE/source。
- [ ] UI：知识包列表、启停、导入、预览。
- [ ] 测试：CRUD、检索加权。

## 任务 7：产品化

**文件：** `web/server.py`、`web/control_api.py`、`OverviewView.vue`、`ScansView.vue`、新 `InstantAnalysisView.vue`、`report`。

- [ ] 即时分析 API：粘贴代码/单文件写入临时仓库并启动扫描。
- [ ] Dashboard API：verified/plausible/rejected、路径覆盖、工具健康、tokens。
- [ ] HTML 报告端点（escape）；证据包 zip（脱敏）。
- [ ] UI：即时分析页、Dashboard 卡片、报告下载按钮。
- [ ] 测试：即时分析、HTML escape、证据包不含密钥。

## 任务 8：全量验证与文档

- [ ] pytest/ruff/mypy/frontend build。
- [ ] Playwright 工作台/即时分析/知识包。
- [ ] 真实 JVWA 重扫（OSS=true）验证 live findings + harness（如可用）。
- [ ] kvf ready 尝试（若允许）。
- [ ] implementation + review-1/2 + README/agent.md。

## 审查重点

1. stop/pause 不产生僵尸线程。
2. SSE seq 连续、刷新可回放。
3. 工具 argv 注入/网络。
4. Harness 镜像/运行时错误不伪造 verified。
5. 知识包/证据包脱敏。
6. 工作台性能与内存。
