# A3/A4 + B1/B2 规格：Agent 过程可见 + 真实 Docker/PoC 实证

> 日期：2026-10-22。上游：`docs/superpowers/specs/2026-10-22-requirements-understanding-audit.md`。本轮遵循既有流水线：spec → spec 审计 → plan → plan 审计 → 实现 → 两轮 review → 文档。

## 1. 范围

### A3 Agent 过程可见

1. 每个节点写 `agent_artifacts`：输入/输出摘要、SHA-256、模型、tokens、`prev_sha256` 哈希链。
2. Triage/PoC 输出带 `tool_trace`：工具名、参数、输出摘要、轮次；落 `findings.tool_trace`。
3. API：`GET /api/scans/{id}/artifacts`、`GET /api/scans/{id}/artifacts/verify`、`GET /api/scans/{id}/findings`、`GET /api/findings/{id}`。
4. Vue `ScanDetail` 增加“审查链”tab：节点卡、输入/输出摘要、模型/tokens、哈希链校验；Finding 抽屉展示 `confidence_parts`、`tool_trace`、`verification_method/nonce`。

### A4 实时事件

1. 节点开始/结束发布事件：`node.start`、`node.end`（状态/耗时/tokens/error）。
2. WebSocket `/ws/scans/{id}` 实时推送；事件总线按 scan_id 缓冲，有订阅者时 drain，避免内存泄漏。
3. 前端 ScanDetail 连接 WS，实时更新时间线并展示最近事件。

### B1 真实 Docker 部署

1. 上传 Web 代码包后默认部署；`POC_RUN` 只控制 PoC 执行，不控制是否部署。
2. 默认 `host` 模式：容器端口发布到 `127.0.0.1` 随机端口，`target_url` 可访问；可选 `internal` 严格沙箱。
3. 构建优先级：项目 `Dockerfile` → 语言配方（python/php/js）。
4. 递归解析 zip 根目录（支持 `web/app.py` 这类单层/双层根）。
5. 端口探测：Dockerfile `EXPOSE`、`app.py` 常见 `port=`/`:port`，否则配置默认端口。
6. 语言配方使用临时可写工作区（不修改上传源）；Dockerfile 使用构建产物。
7. 扫描结束默认清理容器/网络/工作区；`DEPLOY_KEEP=true` 可保留供人工检查。
8. 部署字段写回 `scans`：`deploy_status`、`deploy_log`、`target_url`。

### B2 PoC 实证

1. PoC 必须自身声明 `{CANARY_CMD}` / `{CANARY_FILE}` / `{CANARY_URL}`；无占位符最高 `plausible`。
2. `{CANARY_CMD}` 替换为 `echo CODESENTRY-{nonce}`，PoC 执行输出含 nonce → `verified`。
3. `{CANARY_FILE}` 替换为 `/tmp/codesentry-{nonce}`，检查存在。
4. `{CANARY_URL}` 使用宿主一次性 listener（host 模式）；internal 模式不可用则回退其他占位符。
5. 结果写 `findings.verification_method` / `verification_nonce` / `execution_log`。

## 2. 配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `CODESENTRY_DEPLOY_ENABLED` | true | 上传后是否部署 |
| `CODESENTRY_DEPLOY_NETWORK_MODE` | host | host/ internal |
| `CODESENTRY_DEPLOY_PORT` | 8080 | 默认端口 |
| `CODESENTRY_DEPLOY_KEEP` | false | 扫描结束是否保留容器 |
| `CODESENTRY_DEPLOY_PYTHON_IMAGE` | python:3.12-slim | 可指向本地/私有镜像 |
| `CODESENTRY_DEPLOY_PHP_IMAGE` | php:8.3-cli | |
| `CODESENTRY_DEPLOY_JAVASCRIPT_IMAGE` | node:20-slim | |
| `CODESENTRY_POC_RUN` | off | 只控制 PoC 是否执行 |

## 3. 验收

1. 单元/集成测试：部署语义、嵌套根、端口探测、工具循环、artifacts、事件总线、canary。
2. 真实扫描 612/637：host 模式 `deploy_status=ready`，`target_url` 可访问；637 验证发布端口仅 `127.0.0.1:57255->8080/tcp`；扫描结束容器/网络清理。
3. 真实 canary 613：PoC 脚本含 `{CANARY_CMD}`，命令回显命中 `CODESENTRY-4ad65ec5f4fc441d`，`verification_method=canary`；随后清理。
4. 前端构建通过；`/ui/scans/:id` 审查链 tab、时间线实时事件可用。
5. 全量测试与 ruff/mypy 通过。

## 4. 明确不在本轮

- `docker-compose` 多服务编排（检测后给出明确不支持原因）。
- token 级 LLM 流式（本轮是节点级事件）。
- 内网 listener 回调（internal 模式下 HTTP canary 不可达，需 host 模式或额外网络）。
- 多租户、AI 辅助、RAG 五库/GraphRAG（下一批）。
