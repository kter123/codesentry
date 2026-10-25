# 统一框架实施计划与 TODO

**目标：** 在 CodeSentry 现有图上落地统一 Supervisor、事件流、工作台、Harness、工具网关、知识包与产品化。

## 阶段与任务

### Phase 2：运行时与工作台

- [ ] T1 DDL：`agent_events/agent_nodes/scan_controls`（已部分）
- [ ] T2 `scan_control` + 节点边界 pause/stop（已部分）
- [ ] T3 `events.publish_event` + seq + SSE/回放（已部分）
- [ ] T4 Supervisor 节点与白名单动作
- [ ] T5 图改造：path_build→supervisor→audit/triage/report
- [ ] T6 API：events/SSE/agent-tree/pause/resume/stop
- [ ] T7 Workbench Vue3：左树/中流/右上下文/底部 tabs
- [ ] T8 工作台入口与状态/预算/coverage 展示

### Phase 3：Harness 与工具

- [ ] T9 Harness 模板 CWE-78/89/79/22/94/95/502/918/611/1333
- [ ] T10 全语言命令 + 统一 harness 镜像/Dockerfile
- [ ] T11 `extract_function` API/工具
- [ ] T12 工具网关注册表 + 5 工具
- [ ] T13 tool_runs/事件/证据 UI
- [ ] T14 Harness/Tool 安全测试

### Phase 4：知识包

- [ ] T15 knowledge_packs CRUD + 内置包
- [ ] T16 检索加权 + source 标记
- [ ] T17 知识包 UI

### Phase 5：产品化

- [ ] T18 即时分析 API/UI
- [ ] T19 Dashboard 指标
- [ ] T20 HTML 报告
- [ ] T21 证据包导出
- [ ] T22 项目导入（Git/zip）UI 完善

### 验证与文档

- [ ] T23 全量 pytest/ruff/mypy/build
- [ ] T24 Playwright 工作台/即时分析/知识包
- [ ] T25 JVWA 重扫（OSS=true）验证 live findings/事件
- [ ] T26 kvf ready 尝试（授权后）
- [ ] T27 两轮 review + implementation/architecture 文档

## 文件结构

```text
agents/supervisor.py                  # 唯一路由
control/scan_control.py               # pause/stop
orchestrator/events.py                # 事件持久化/回放
orchestrator/telemetry.py             # node → event/agent tree
control/harness.py                    # Harness 执行
control/harness_templates.py          # CWE/语言模板
control/tool_gateway.py               # 外部工具网关
control/knowledge_packs.py             # 知识包
web/control_api.py                    # events/control/tools/knowledge
web/graph_api.py                      # 工作台数据
web/frontend/src/views/WorkbenchView.vue
web/frontend/src/views/InstantAnalysisView.vue
```

## 验收

- 扫描运行中工作台实时显示事件/路径/finding/验证。
- 刷新回放；暂停/恢复/停止。
- Harness verified 可复现；不可用不伪报。
- 工具 unavailable 不阻断；结果只作证据。
- 知识包可检索。
- 全量质量门禁通过。
