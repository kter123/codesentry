# CodeSentry

基于 **LangGraph** 的 LLM 多智能体源码安全审计平台：三引擎静态扫描 → GraphRAG 证据检索 → AI 验证降噪 → 沙箱部署与 PoC 实证 → 人工复核 → 中文审计报告；配套 FastAPI + Vue 3 控制台。

## 当前状态

- M0–M5 已完成：脚手架、三引擎、RAG、六 Agent 流水线、质量评测、WebUI。
- M6.1–M6.5 已完成（2026-10-20）：控制面（LLM Profile / Agent 绑定 / Prompt / Skills / 用量 / 审计 / 认证）、Docker 沙箱部署、PoC canary 实证、Artifacts 审查链、置信度校准、Vue 3 控制台。
- M6.6 部分完成：graph_templates、Prompt 评测记录、SARIF 下载、replay；A/B 自动评测、webhook/通知、多租户与 AI 辅助待续。

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
