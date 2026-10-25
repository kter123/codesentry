# 剩余需求实现计划（P0 + P1）

> **面向执行者：** 逐任务实现；每个任务先写失败测试，再实现，最后跑测试并 commit。任务顺序按依赖排列。

**目标：** 把 CodeSentry 的路径审计、CodeQL 全链路、路径级 PoC/UI、部署、成本控制，以及 P1 的运营/控制面能力全部落地。

**架构：** 保持“代码→图→路径→Agent→Triage→Deploy→PoC→Report”主链；新增能力均通过图查询、Agent 工具、控制面 API/DB 表扩展，不引入第二套分析真值。

**技术栈：** FastAPI、psycopg、LangGraph、Vue3/Element Plus/ECharts、tree-sitter、CodeQL、Docker、pytest。

**规格：** `doc/2026-10-25-remaining-backlog-spec.md` + `doc/2026-10-25-remaining-backlog-spec-audit.md`

## 全局约束

- 不新增 cron/通知第三方依赖；cron 用 stdlib 实现。
- 不硬编码密钥；secret 加密存储，读写掩码；导出排除敏感键。
- Docker 端口仅 `127.0.0.1`；PoC 默认 `off`；不访问远程 target。
- 多租户不做；不修改 `CodeScan-Artex/`；不提交 `kvf-admin-master.zip`。
- 每个任务必须补测试；DB 测试用唯一 scan_id 并清理。

---

## 任务 1：配置、DDL 与路径统计/成本控制

**文件：**
- 修改：`src/codesentry/config.py`
- 修改：`src/codesentry/db/ddl.py`
- 修改：`src/codesentry/control/audit_paths.py`
- 修改：`src/codesentry/agents/path_audit_nodes.py`
- 修改：`src/codesentry/agents/path_audit.py`
- 测试：`tests/test_path_cost.py`

**步骤：**
- [ ] 1.1 写失败测试 `test_claim_prioritizes_proven_and_caps_entry_only`：插入 20 proven / 20 entry_only，`claim_paths(max_paths=5, entry_only_max=1)` 返回 5，首条 proven，entry_only ≤1。
- [ ] 1.2 写失败测试 `test_coverage_reports_dataflow_and_sinks_total`：造带 dataflow 的路径，断言 `dataflow_paths>=1`、`sinks_total>=1`、`pending`。
- [ ] 1.3 `config.py` 增加 `audit_max_paths=240`、`audit_entry_only_max=48`、`audit_path_timeout_s=60`、`audit_priority="proven_first"`。
- [ ] 1.4 `audit_paths.claim_paths(scan_id, limit=8, lease_s=900, *, max_paths=None, entry_only_max=None)`：CTE 统计已审计数；排序 `proven/likely/weak`、非 entry-only 优先、score DESC；超限返回空/截断。
- [ ] 1.5 `coverage(scan_id)` 返回 `total/pending/auditing/finding/clean/blocked/error/entry_only/dataflow_paths/batch/max_rounds/entries_covered/sinks_covered/sinks_total`；`sinks_total` 从 `graph_nodes` + scans.repo_path 解析 project 查询。
- [ ] 1.6 `run_audit_plan` 传配置上限；`run_path_audit` 使用 `audit_path_timeout_s`。
- [ ] 1.7 `run_audit_collect` coverage 增加 `batch/pending/dataflow_paths`。
- [ ] 1.8 运行 `pytest tests/test_path_cost.py tests/test_path_audit.py tests/test_path_graph.py -q`。

## 任务 2：CodeQL 多语言 + URI 归一 + SARIF 解析修正

**文件：**
- 修改：`src/codesentry/models.py`（EngineResult 增 `lang`、`artifact`）
- 修改：`src/codesentry/engines/codeql.py`
- 修改：`src/codesentry/engines/codeql_graph.py`
- 修改：`src/codesentry/agents/scan.py`
- 修改：`src/codesentry/scan_orchestrator.py`
- 测试：`tests/test_codeql_multilang.py`

**步骤：**
- [ ] 2.1 测试 `normalize_uri_file_absolute_encoded`：`file:///repo/a%20b.py`、绝对路径、相对路径都归一到 `a b.py`；越界返回空。
- [ ] 2.2 测试 `parse_sarif_repo_uri`：SARIF `uri=file://.../Cmd.java` 解析出的 finding.file 为相对路径。
- [ ] 2.3 `EngineResult` 增加 `lang: str = ""`、`artifact: str = ""`。
- [ ] 2.4 `codeql._parse_sarif(path, repo=None)`：按 run 取 rules；URI 归一；`Finding(engine="codeql")`。
- [ ] 2.5 `run_codeql` 返回 `lang=db_lang, artifact=str(result_sarif)`；数据库/SARIF 文件名用 `db_lang`。
- [ ] 2.6 `scan_orchestrator` 增 `codeql_langs(languages)`：归一 `javascript/typescript`、去重、排除 php。
- [ ] 2.7 `run_scan_agent`：Semgrep 1 个 spec；CodeQL 每语言 1 个 spec；Joern 只在有 java 时 1 个。spec 名含语言，异常可按引擎识别。
- [ ] 2.8 收集所有 `result.artifact`（或 work 下 `codeql-<lang>.sarif`），逐个 `run_codeql_graph(..., build_id=state.graph_build_id)`；合并 `engine_graph.codeql` 统计。
- [ ] 2.9 运行 `pytest tests/test_codeql_*.py tests/test_engine_graph.py tests/test_agent_led_pipeline.py -q`。

## 任务 3：路径级 PoC

**文件：**
- 修改：`src/codesentry/agents/poc_gen.py`
- 修改：`src/codesentry/sandbox/verify.py`
- 修改：`src/codesentry/agents/triage.py`（保留 path_id/path_nodes）
- 测试：`tests/test_path_poc.py`

**步骤：**
- [ ] 3.1 测试 `path_context_contains_entry_and_url`：插入 audit_paths + graph_nodes endpoint（attrs.method/route），`_path_context` 返回 method/route/full_url。
- [ ] 3.2 测试 `gen_poc_prompt_includes_path_context`：fake LLM 捕获 user，断言 `path_context`、`path_id`。
- [ ] 3.3 测试 `poc_entry_url_absent_without_target`：无 target_url 时 `entry_url=""`，不出现臆造 host。
- [ ] 3.4 实现 `_path_context(scan_id, finding)`：查 audit_paths；解析 entry/source/sink 的 graph_nodes；`entry_url = target_url.rstrip('/') + route` 仅当 route 以 `/`。
- [ ] 3.5 `gen_poc(..., path_context=None)` 合并 user JSON，system 增加“以 path_context 为准、HTTP 必须含 {CANARY_URL}”。
- [ ] 3.6 `run_poc_gen` 对每条 finding 取 path_context，结果写 `path_id/entry_url`。
- [ ] 3.7 `verify_listener` 监听 `0.0.0.0`，回调 host 可配 `CODESENTRY_CANARY_HOST`（默认 `host.docker.internal`），替换 `{CANARY_URL}`。
- [ ] 3.8 运行 `pytest tests/test_path_poc.py tests/test_poc_gen.py -q`。

## 任务 4：路径详情 API + 扫描详情 UI + 图高亮

**文件：**
- 修改：`src/codesentry/web/graph_api.py`
- 修改：`web/frontend/src/views/ScanDetailView.vue`
- 修改：`web/frontend/src/views/GraphView.vue`
- 测试：`tests/test_path_api.py`

**步骤：**
- [ ] 4.1 API 测试：`/paths/{pid}` 返回 `nodes_detail/edges_detail`；`/graph?focus=key` 包含 focus 节点。
- [ ] 4.2 `graph_api` 新增 `_path_detail`：按 path.nodes 查 graph_nodes，按 path.edges 原样返回 + `src/dst` 的 kind/name。
- [ ] 4.3 `/graph` 新增 `focus` 参数：先查 focus 节点，再补普通节点，去重后 limit。
- [ ] 4.4 `ScanDetailView` 路径表加统计 tags（total/pending/entry-only/proven/batch/sink covered/total），行点击打开抽屉；抽屉展示节点表、边表、证据 JSON、源码切片、`在图中高亮`。
- [ ] 4.5 `GraphView` 读取 `route.query.path_id`，请求路径详情；`load()` 时带 `focus`；highlight set 用于节点描边/边加粗/非路径降透明；显示清除按钮。
- [ ] 4.6 前端 `npm run build`。

## 任务 5：Deploy 本地镜像、war、依赖降级

**文件：**
- 修改：`src/codesentry/sandbox/deploy.py`
- 修改：`src/codesentry/agents/deploy_agent.py`（如需提示）
- 测试：`tests/test_deploy_hardening.py`

**步骤：**
- [ ] 5.1 测试 `ensure_image_never_does_not_pull`：mock docker，`policy=never` 且本地缺失 → disabled/异常，不调用 pull。
- [ ] 5.2 测试 `maven_command_supports_war`：命令包含 `war` 分支。
- [ ] 5.3 测试 `missing_db_dependency_is_degraded`：日志含 `MySQL` 且健康失败 → status=degraded。
- [ ] 5.4 实现 `_ensure_image(client, image, policy)`：`never/missing/always`；本地存在跳过 pull；缺失按策略。
- [ ] 5.5 Maven 命令：`mvn -q -DskipTests package`；jar→`java -jar`；war→`tomcat` 本地镜像可用则 `catalina.sh run`，否则复制 war 到 `/usr/local/tomcat/webapps/ROOT.war`。
- [ ] 5.6 `detect_db_dependency(root)`：扫描 `application*.yml/properties` 的 mysql/redis；构建成功但健康失败时在日志加“缺少 MySQL/Redis 依赖”。
- [ ] 5.7 所有镜像使用前走 `_ensure_image`；`deploy_image_pull` 生效。
- [ ] 5.8 运行 `pytest tests/test_deploy_*.py -q`。

## 任务 6：通知渠道（generic/feishu/dingtalk/wecom/email）

**文件：**
- 修改：`src/codesentry/db/ddl.py`
- 修改：`src/codesentry/control/webhooks.py`
- 新建：`src/codesentry/control/notifications.py`
- 修改：`src/codesentry/web/server.py`（settings group）
- 修改：`src/codesentry/web/control_api.py`
- 修改：`web/frontend/src/views/SettingsView.vue`
- 测试：`tests/test_notifications.py`

**步骤：**
- [ ] 6.1 DDL：webhooks 增 `name TEXT`、`kind TEXT DEFAULT 'generic'`、`headers JSONB DEFAULT '{}'`、`last_status TEXT`、`last_error TEXT`、`last_sent_at TIMESTAMPTZ`。
- [ ] 6.2 测试四种 payload/签名；测试 secret 加密（`enc:`）且 list 不含 secret；测试 email 用 mock smtp。
- [ ] 6.3 `webhooks`：`_decrypt_secret`、`_encrypt_secret`；`create_webhook(name,url,secret,events,kind,headers)`；`dispatch` 按 kind 构造 `_payload_for`；失败写 last_error。
- [ ] 6.4 `notifications.dispatch_all(event,payload)`：webhooks + SMTP；`settings/notifications` 键 `smtp_host/smtp_port/smtp_user/smtp_password/smtp_from/smtp_to/smtp_tls`，password 加密。
- [ ] 6.5 API：webhook list/create/delete/test；settings notifications get/put/test；`/api/webhooks/{id}/test`。
- [ ] 6.6 Settings UI 增加通知渠道表格与新增表单（kind/name/url/secret/events）、测试/删除；SMTP 表单。
- [ ] 6.7 运行 `pytest tests/test_notifications.py tests/test_webhooks.py tests/test_web_server.py -q`。

## 任务 7：项目与定时扫描

**文件：**
- 修改：`src/codesentry/db/ddl.py`
- 新建：`src/codesentry/control/projects.py`
- 新建：`src/codesentry/control/scheduler.py`
- 新建：`src/codesentry/web/projects_api.py`
- 修改：`src/codesentry/web/server.py`（import + startup）
- 新建：`web/frontend/src/views/ProjectsView.vue`
- 修改：`web/frontend/src/router/index.ts`、`AppLayout.vue`
- 测试：`tests/test_projects.py`

**步骤：**
- [ ] 7.1 测试 cron：`*/5 * * * *`、`0 3 * * *`、`1,15 * * * *`、非法表达式。
- [ ] 7.2 测试项目路径必须 work 根内；git_url 非 https/私网拒绝。
- [ ] 7.3 DDL：projects、scan_schedules。
- [ ] 7.4 `projects.py`：CRUD、`cron_next(cron, after)`、`claim_due_schedules(now)` 原子 update。
- [ ] 7.5 `scheduler.py`：后台 daemon 线程每 `scheduler_interval_s` 调用 `claim_due_schedules`；有 repo_path 直接 `_insert_scan` + `_run_scan_bg`；git_url 用 clone helper。
- [ ] 7.6 `projects_api.py`：/api/projects CRUD、/api/schedules CRUD、/api/schedules/{id}/run；admin 写。
- [ ] 7.7 前端页面：项目表、schedule 表、创建/启停/立即运行；路由 `/projects` 与菜单。
- [ ] 7.8 运行 `pytest tests/test_projects.py tests/test_web_e2e.py -q`。

## 任务 8：自定义 Agent Preset

**文件：**
- 修改：`src/codesentry/db/ddl.py`
- 新建：`src/codesentry/control/agent_presets.py`
- 修改：`src/codesentry/control/agent_config.py`
- 修改：`src/codesentry/agents/runtime.py`
- 修改：`src/codesentry/web/control_api.py`
- 修改：`web/frontend/src/views/AgentDetailView.vue`
- 测试：`tests/test_agent_presets.py`

**步骤：**
- [ ] 8.1 测试 preset 绑定后 `prepare_agent.system()` 含 preset 正文 + invariant tail；解绑恢复。
- [ ] 8.2 测试非法 base_agent 返回 ValueError。
- [ ] 8.3 DDL：agent_presets；agent_configs 增 `preset_id`。
- [ ] 8.4 `agent_presets.py`：list/get/create/update/delete/bind；版本自增。
- [ ] 8.5 `agent_config._EDITABLE` 加 `preset_id`；`get_agent_config` 读取。
- [ ] 8.6 `runtime.prepare_agent`：若 `preset_id`，加载 preset，`compose_prompt(agent, preset.system_prompt, force_tail=True)`；合并 tools/skills/capabilities；snapshot 加 preset 信息。
- [ ] 8.7 API：/api/agent-presets CRUD、/api/agents/{name}/bind-preset；AgentDetail 增加选择/编辑。
- [ ] 8.8 运行 `pytest tests/test_agent_presets.py tests/test_agent_config.py tests/test_agent_runtime.py -q`。

## 任务 9：Agent 试跑对比

**文件：**
- 修改：`src/codesentry/web/control_api.py`
- 修改：`web/frontend/src/views/AgentDetailView.vue`
- 测试：`tests/test_agent_compare.py`

**步骤：**
- [ ] 9.1 测试 dry-run compare 返回 a/b system_prompt、token_est、diff，不调用 LLM。
- [ ] 9.2 测试非法版本 400。
- [ ] 9.3 API `/api/agents/{name}/compare`：`state/prompt_a/prompt_b/use_llm`；dry-run 或受控 LLM。
- [ ] 9.4 AgentDetail 增加“试跑对比”对话框（两个版本下拉、dry-run 开关、diff 展示）。
- [ ] 9.5 运行测试 + 前端 build。

## 任务 10：配置导入导出

**文件：**
- 新建：`src/codesentry/control/config_io.py`
- 修改：`src/codesentry/web/control_api.py`
- 修改：`web/frontend/src/views/SettingsView.vue`
- 测试：`tests/test_config_io.py`

**步骤：**
- [ ] 10.1 测试 export 不含 `api_key/secret/codeql_build_command`。
- [ ] 10.2 测试 import merge/replace、非法 JSON 400、replace 不删 llm_profiles。
- [ ] 10.3 `config_io.export_config()`：prompts/agents/presets/skills/templates/webhooks（无 secret）/settings（非敏感）。
- [ ] 10.4 `config_io.import_config(doc, mode)`：逐项校验；敏感键强制空；返回 counts/errors。
- [ ] 10.5 API GET/POST，admin；UI 导出下载/导入文件。
- [ ] 10.6 运行测试。

## 任务 11：报告路径可视化

**文件：**
- 修改：`src/codesentry/agents/report.py`
- 修改：`src/codesentry/reportex/sarif.py`（properties 加 path_id）
- 测试：`tests/test_report_paths.py`

**步骤：**
- [ ] 11.1 测试报告含“攻击路径”、Mermaid、entry/sink、无路径时空态。
- [ ] 11.2 `_path_section(state)`：仅 scan_id>0 查 audit_paths；输出表格 + Mermaid（节点截断 20）。
- [ ] 11.3 `run_report` 追加章节；SARIF properties 写 path_id。
- [ ] 11.4 运行测试。

## 任务 12：图 package 折叠

**文件：**
- 修改：`web/frontend/src/views/GraphView.vue`
- 测试：`web/frontend` build（无单测框架，使用 build + smoke）。

**步骤：**
- [ ] 12.1 增加 `groupByPackage` 开关与 `aggregatedGraph` computed；包节点 `pkg:<dir>`，边聚合计数。
- [ ] 12.2 渲染使用 `visibleNodes/visibleEdges` 的来源切换；点击包节点关闭聚合并设置 search=包目录。
- [ ] 12.3 图统计显示“包/原始节点/边”；构建通过。

## 任务 13：生命周期清理

**文件：**
- 修改：`src/codesentry/control/retention.py`
- 修改：`src/codesentry/web/control_api.py`
- 修改：`web/frontend/src/views/SettingsView.vue`
- 测试：`tests/test_retention.py`

**步骤：**
- [ ] 13.1 测试 purge_scans 删除 audit_paths/audit_rounds/review_comments/agent_artifacts。
- [ ] 13.2 测试 codeql cache/orphan workdir 只删过期项。
- [ ] 13.3 实现 `cleanup_codeql_cache(days)`、`cleanup_orphan_workdirs(days)`、`cleanup_target_images(scan_ids=None)`。
- [ ] 13.4 API `/api/ops/maintenance`；UI 设置页维护按钮 + 磁盘统计。
- [ ] 13.5 运行测试。

## 任务 14：SDK 补全

**文件：**
- 修改：`src/codesentry/sdk.py`
- 测试：`tests/test_sdk.py`

**步骤：**
- [ ] 14.1 测试 `list_paths/get_path/coverage/codeql_status/export_config` 的 URL 与返回。
- [ ] 14.2 实现方法。
- [ ] 14.3 运行测试。

## 任务 15：浏览器 smoke、回归数据集、全链路验证脚本

**文件：**
- 新建：`scripts/ui_smoke_safari.py`
- 新建：`tests/fixtures/path_eval.json`
- 新建：`tests/fixtures/codeql/CmdServlet.java`、`py_cmd.py`、`js_cmd.js`
- 新建：`scripts/validate_codeql_fullchain.py`
- 修改：`scripts/eval_path_audit.py`、`tests/test_path_eval_regression.py`
- 文档：`doc/2026-10-25-remaining-backlog-implementation.md`、review-1/2、架构更新。

**步骤：**
- [ ] 15.1 Safari WebDriver smoke：启动后端/前端，逐路由检查 `#app` 子节点、标题、console error；失败输出 BLOCKED。
- [ ] 15.2 路径 eval 数据集与离线回归测试。
- [ ] 15.3 CodeQL 全链路脚本：上传 synthetic repo → poll scan → 校验 findings/graph/paths。
- [ ] 15.4 真实运行：Java/Python/JS CodeQL；kvf 部署；记录结果到 implementation 文档。
- [ ] 15.5 全量 `pytest`、ruff、mypy、前端 build；两轮 code review 文档；commit + push。

## 审查重点

1. **密钥泄露**：webhook secret、SMTP password、导出文件、日志。任何新增返回必须排除 secret/cipher。
2. **路径穿越/SSRF**：project.repo_path、git_url、通知 webhook URL、source 读取。
3. **并发/重复扫描**：scheduler 多 worker、claim_paths 并发、CodeQL 同名 SARIF 覆盖。
4. **成本失控**：entry-only 路径、compare 真实 LLM、maintenance 误删。
5. **兼容/降级**：CodeQL 单语言失败、无 Docker、无浏览器、旧 webhook 明文 secret、旧无 path_id finding。
