# P2 安全扩展实现计划

**目标：** 部署 Agent 自主依赖、JS 匿名回调图节点、CodeQL 预授权自动安装、修复建议、受限远程目标探测；不做反弹/交互 shell。

**规格：** `doc/2026-10-25-p2-safe-extensions-spec.md` + spec-audit

## 任务 1：部署依赖编排

**文件：** `config.py`、`sandbox/dependencies.py`（新）、`sandbox/deploy.py`、`agents/deploy_agent.py`、`models`/DDL 无需。

- [ ] 测试 `detect_dependencies` 识别 mysql/redis/postgres。
- [ ] 测试 `ensure_dependency`：never 缺镜像不 pull；missing 拉；失败返回 degraded reason。
- [ ] 配置：`deploy_auto_dependencies=true`、`deploy_dependency_images`、`deploy_dependency_timeout_s=90`。
- [ ] `DependencyManager`：与目标同 network，容器名 `codesentry-dep-<scan>-<kind>`，alias `mysql/redis/postgres`；env 注入；健康等待；清理。
- [ ] `DockerDeployer` 在目标启动前调用依赖编排；`meta.dependencies`；失败 degraded。
- [ ] `DeploySession` 增工具 `detect_dependencies`/`ensure_dependency`；system prompt 指示 Agent 自主决定。
- [ ] 验收：mock Docker 单测；kvf 真实尝试记录。

## 任务 2：JS/TS 匿名回调节点

**文件：** `rag/extractors/generic.py`、`tests/test_js_anon.py`。

- [ ] 失败测试：Express fixture 生成 `function:*anon@L3`，endpoint→function `routes_to`，sink contains。
- [ ] `_function` 无 name 且 JS/TS → `_add_function(node, f"anon@L{line}", ...)`。
- [ ] `_routes.owner` 支持路由行到下一行开始的匿名函数。
- [ ] 去重 key。
- [ ] 代码图/路径测试：endpoint→anon→sink feasibility=proven（有 dataflow 时）。

## 任务 3：CodeQL 预授权自动安装

**文件：** `config.py`、`control/engine_install.py`（新）、`engines/codeql.py`、`agents/scan.py`、`web/control_api.py`、`SettingsView.vue`、测试。

- [ ] 测试 URL 白名单、未 ack 拒绝、sha 不匹配拒绝、解压路径穿越拒绝。
- [ ] `install_codeql(version, license_ack, sha256)`：固定 GitHub release URL；流式下载到临时文件；sha 校验；安全解压；`codeql version` 验证；原子移动到目标目录；audit。
- [ ] API `POST /api/engines/codeql/install` + status；settings 加 auto_install/version/license_ack/install_dir/sha。
- [ ] `scan` 在 OSS + binary 缺失 + auto_install + license_ack 时自动安装，失败降级。
- [ ] Settings UI 增加安装按钮/版本/许可 ack/自动安装开关。
- [ ] 真实安装可选 live；限时。

## 任务 4：修复建议（只产 patch）

**文件：** `agents/fix_agent.py`（新）、DDL、`web/control_api.py`、`ScanDetailView.vue`、测试。

- [ ] 测试 patch 安全校验拒绝危险模式；404/503。
- [ ] `generate_fix(llm, finding, source, graph)`：输出 summary/patch/tests/risk；prompt 明确“只输出 unified diff，不改源码”。
- [ ] DDL `findings.fix_patch/fix_summary/fix_tests`；API `POST /api/findings/{id}/fix`；admin/analyst 写。
- [ ] UI Finding 抽屉“生成修复建议”按钮 + patch 展示；不自动应用。
- [ ] 无 LLM 返回 503。

## 任务 5：受限远程目标

**文件：** DDL `poc_targets`、`control/poc_targets.py`（新）、`web/control_api.py`、`auth.py`、测试。

- [ ] 测试私网拒绝、过期拒绝、host 不匹配拒绝、probe 只 GET/HEAD。
- [ ] `poc_targets` 表 + CRUD；URL 校验（https，默认禁私网，allow_private 开关）。
- [ ] `POST /api/poc-targets/{id}/probe`：单次 GET/HEAD `/`，5s 超时，记录状态；不执行 finding payload。
- [ ] 配置 `poc_remote_enabled=false`、`poc_remote_allow_private=false`；未开启 403。
- [ ] 不实现反弹/交互 shell；测试断言 `check_payload_safety` 拒绝相关模式。

## 任务 6：验证与文档

- [ ] 单测全绿；ruff/mypy；前端 build。
- [ ] 真实 kvf 依赖尝试；JS 图路径验证。
- [ ] `doc/2026-10-25-p2-safe-extensions-implementation.md` + review-1/2。
- [ ] 更新 README/agent.md；commit/push。

## 审查重点

1. 依赖镜像不得绕过 pull 策略/allow_remote。
2. CodeQL 下载 host/重定向/解压/许可。
3. 远程 target 私网/重定向/并发/超时。
4. patch 不落源码、无危险命令。
5. 清理依赖容器/网络。
6. 匿名节点不重复、路由行匹配。
