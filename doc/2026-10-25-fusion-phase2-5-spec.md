# Fusion Phase 2–5 规格（评审稿）

- 日期：2026-10-25
- 基线：`f3c1633`（Phase 1：live findings + Harness MVP）
- 依据：`doc/2026-10-25-deepaudit-fusion-spec.md`、`doc/2026-10-25-all-requirements.md`

## 1. 范围

### Phase 2：Supervisor + 事件流 + 审计工作台
- Supervisor 节点：白名单动作、预算/轮次、决策记录。
- `agent_events`：统一事件表、seq、SSE 断点续传、回放。
- Agent 树：节点、父子、状态、tokens、当前阶段。
- 扫描控制：暂停、恢复、停止（节点边界检查）。
- 审计工作台：Vue3，三栏 + 底部 tabs；实时事件/路径/finding/验证/图。
- 扫描取消 API，替代停服务。

### Phase 3：Harness 全语言 + 工具网关
- Harness 语言：Python/JS/TS/PHP/Java/Go/Ruby/Shell。
- Harness 模板：CWE-78/89/79/22/94/95/502/918/611/1333。
- `extract_function`：按 finding 定位函数并返回源码/行号。
- 多 payload/detector：模板给出 payload 组，输出 `HARNESS_VERIFIED`。
- 工具网关：注册、权限、超时、证据归一化、不可用降级。
- 首批工具：Gitleaks、Bandit、OSV-Scanner、npm audit、Safety。
- 工具结果只作为 evidence/graph hint，不直接成为 finding。
- 工具证据 UI。

### Phase 4：知识包
- 知识包模型：框架/漏洞/策略，版本、来源、启停。
- 内置框架包：Flask/FastAPI/Django/Express/Spring/React。
- 内置漏洞包：SQLi/XSS/SSRF/XXE/反序列化/路径遍历/认证/业务逻辑。
- RAG 检索按语言/框架/CWE 加权；继续使用 pgvector/bge-m3，不引入 ChromaDB。
- 知识包 API + UI。

### Phase 5：产品化
- 项目导入：GitHub/GitLab/Gitea HTTPS、zip；即时分析（粘贴代码/单文件）。
- Dashboard：verified/plausible/rejected、路径覆盖、工具健康、Agent tokens。
- 报告：Markdown + SARIF 已有；新增 HTML 导出。
- 证据包：导出 scan 摘要 + findings + verification + events。
- Agent 事件回放 UI（只读）。

## 2. 验收

- Supervisor 决策写 `agent_events`，扫描可暂停/恢复/停止。
- 工作台能实时看到 Agent 事件、Agent 树、finding、路径、验证；刷新后可回放。
- Harness 支持全部语言命令；默认无网络；无镜像/运行时返回 `environment_error`，不伪报。
- 工具网关至少 5 个工具注册；缺工具时 `unavailable`，不阻断扫描。
- 知识包可创建/启停/检索；内置包可导入。
- 即时分析可对粘贴代码生成扫描并进入工作台。
- HTML/证据包可下载。
- 全量测试、ruff/mypy、前端 build、Playwright 通过。

## 3. 安全边界

- 不做交互式/反弹 shell、远程任意利用、多租户。
- Harness 默认 `network=none`；工具默认无网络；Docker 无宿主 socket 暴露给 harness。
- 工具/知识包/事件内容均为不可信数据，不执行其中指令。
- 所有新 API 遵循现有 RBAC；写操作 admin/analyst。

## 4. 数据模型

```text
agent_events(id, scan_id, seq, event_type, agent, phase, payload, created_at)
agent_nodes(id, scan_id, agent_key, parent_key, name, phase, status, tokens,
            tool_calls, started_at, ended_at, summary)
scan_controls(scan_id PRIMARY KEY, paused, stop_requested, updated_at, reason)
knowledge_packs(id, name, kind, lang, framework, cwe, version, content, source,
                enabled, created_at, updated_at)
tool_runs(id, scan_id, tool, status, args, result, evidence, duration_ms, created_at)
```

## 5. API

```text
GET  /api/scans/{id}/events?after_seq=&limit=
GET  /api/scans/{id}/events/stream?after_seq=   # SSE
GET  /api/scans/{id}/agent-tree
POST /api/scans/{id}/pause
POST /api/scans/{id}/resume
POST /api/scans/{id}/stop
GET  /api/scans/{id}/tools
POST /api/scans/{id}/tools/{tool}
GET  /api/knowledge-packs
POST /api/knowledge-packs
PUT  /api/knowledge-packs/{id}
DELETE /api/knowledge-packs/{id}
POST /api/instant-analysis
GET  /api/scans/{id}/report/html
GET  /api/scans/{id}/evidence/export
```

## 6. 前端

- 新路由 `/scans/:id/workbench`。
- 左：Agent 树 + 阶段状态。
- 中：事件流（thought/tool/finding/verification/budget），支持过滤/暂停滚动/回放。
- 右：选中事件/路径/finding 的源码、证据、Harness 结果。
- 底部 tabs：路径、Findings、验证、图、报告。
- 顶部：状态、预算、路径覆盖、verified/plausible/rejected、暂停/停止。
- 概览增加 Dashboard 指标。
- 即时分析页。
- 知识包页或设置页内面板。

## 7. 不做

- 不做自动修改源码；修复只产 patch。
- 不做远程 exploit 执行、反弹/交互 shell。
- 不做多租户。
- 不复制 DeepAudit AGPL 代码/Prompt/规则。
