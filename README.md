# CodeSentry

基于 **LangGraph** 的 LLM 多智能体源码安全审计平台：三引擎静态扫描 → GraphRAG 证据检索 → AI 验证降噪 → 沙箱部署与 PoC 实证 → 人工复核 → 中文审计报告；配套 FastAPI + Vue 3 控制台。

## 当前状态

- M0–M5 已完成：脚手架、三引擎、RAG、六 Agent 流水线、质量评测、WebUI。
- M6.1–M6.5 已完成（2026-10-20）：控制面（LLM Profile / Agent 绑定 / Prompt / Skills / 用量 / 审计 / 认证）、Docker 沙箱部署、PoC canary 实证、Artifacts 审查链、置信度校准、Vue 3 控制台。
- M6.6 部分完成：graph_templates、Prompt 评测记录、SARIF 下载、replay；A/B 自动评测、webhook/通知、多租户与 AI 辅助待续。
- 2026-10-23 图谱核心（G1–G4）：六语言 tree-sitter 抽取、项目级增量图构建、`graph_build` 节点、真实向量检索、GraphRAG 查询 API 与 Agent 图工具、力导向图页面。
- 2026-10-23 管理面（M1–M2）：Prompt 三段式（可编辑正文 + 代码固定尾 + 变量）、Agent 工具/技能白名单、LLM 优先级池与熔断、原始调用记录。
- 2026-10-24 路径中心审计：引擎→图 → sink 反向路径 → 多轮 Agent 路径审计 → Triage → DeployAgent → PoC；Agent/Prompt 全可配置；RAG 工具化。
- 2026-10-24 引擎 Dataflow 入图：Joern calls/dataflow、CodeQL codeFlows 写入图；entry-only 入口审计路径；本地 bge-m3（1024 维）真实入库。
- 2026-10-25 统一审计框架：Supervisor 白名单调度、agent_events/SSE/Agent 树、暂停恢复停止、Vue3 审计工作台、Harness 模板/全语言命令、工具网关、知识包、即时分析/HTML 报告/证据包。
- 2026-10-25 P2 安全扩展：部署 Agent 自动依赖（MySQL/Redis/PostgreSQL）、JS 匿名回调节点、CodeQL 预授权自动安装、修复建议（只产 patch）、受限远程目标只读探测；交互式/反弹 shell 明确不实现。
- 2026-10-25 P0/P1 收口：CodeQL 多语言全链路（Java/Python/JS）、路径级 PoC、路径抽屉与图高亮、审计成本上限、通知渠道（飞书/钉钉/企微/邮件）、项目/定时扫描、自定义 Agent Preset、Agent 试跑对比、配置导入导出、报告路径图、图包聚合、生命周期维护、SDK 补全。

## 快速开始

```bash
docker compose up -d          # PostgreSQL 16 + pgvector
uv sync
uv run codesentry init-db
uv run uvicorn codesentry.web.server:app --host 127.0.0.1 --port 8000
```

- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`GET /api/health`
- LLM 配置：在 WebUI 的 LLM Profile 页面创建（密钥加密落库、只回显掩码），或使用 `.env` 兜底。

## 认证

默认 `CODESENTRY_AUTH_ENABLED=false`（本地单机）。开启后：

```bash
export CODESENTRY_AUTH_ENABLED=true
export CODESENTRY_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
export CODESENTRY_ADMIN_PASSWORD='change-me'
uv run codesentry user create admin --admin   # 或用 ADMIN_PASSWORD 引导
```

角色：`admin` / `analyst` / `viewer`；CI 使用 `cs_...` API Token（scope `scan:read` / `scan:write`）。

## 开发

```bash
uv run pytest -q             # 全量（默认不跑 live）
uv run ruff check src tests
uv run mypy src
OPENCODE_GO_API_KEY=... uv run pytest -m live tests/test_opencode_probe.py -q
```

## 文档

- 需求基线：`docs/superpowers/specs/2026-10-19-requirements-v2.md`
- M6.1 规格/计划/架构：`doc/2026-10-20-m6.1-platform-foundation-spec.md`、`...-plan.md`、`...-architecture.md`
- LLM Provider：`docs/superpowers/specs/2026-10-20-opencode-go-provider-design.md`
- 原始需求与里程碑：`agent.md`

## 安全边界

- PoC 默认不执行（`CODESENTRY_POC_RUN=off`）；开启后仅限授权沙箱/目标容器。
- 不建立、不保留真实交互式 shell；验证使用 canary/回调/文件副作用。
- API Key 加密存储，读接口掩码；日志/报告/导出不含完整密钥。
- 上传 zip 防路径穿越（≤500MB），git 仅 https。
