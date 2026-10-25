# P2 安全扩展规格（2026-10-25）

## 范围与安全边界

### 做
1. **部署 Agent 自主依赖决策**：识别 MySQL/Redis/PostgreSQL，自动启动依赖容器、按策略拉镜像、注入 env，目标应用自启动验证。
2. **JS/TS 匿名回调图节点**：生成合成函数节点，路由连接匿名回调，路径从 weak 提升为 proven。
3. **CodeQL 自动安装（预授权）**：固定版本、SHA256 校验、管理员许可确认；扫描/管理面可在预授权后自动安装，不静默绕过许可。
4. **自动修复建议**：只生成 unified diff + 说明 + 建议测试，不自动写回源码；人工确认后才可应用。
5. **远程 PoC target（受限）**：目标登记、授权范围/过期、只读探测/带 canary 回调的 HTTP 请求；默认关闭，不允许私网/任意 host。
6. **交互式/反弹 shell**：**不实现**。保留现有非交互、固定 argv、超时、无外联的沙箱执行。

### 不做
- 远程目标任意利用、批量目标、持久化、反弹 shell、交互式 shell、绕过授权/审计。
- CodeQL 静默下载或绕过许可 Gate。
- 自动修改用户源码（只产 patch）。

## 1. 部署 Agent 自主依赖

### 需求
- 配置：
  - `deploy_auto_dependencies: bool = True`
  - `deploy_dependency_images: {mysql: "mysql:8.0", redis: "redis:7-alpine", postgres: "postgres:16-alpine"}`
  - `deploy_dependency_pull: never|missing|always`（复用 `deploy_image_pull` 默认）
  - `deploy_dependency_timeout_s: int = 90`
- 检测：`application*.yml/properties` 中 `mysql`/`redis`/`postgres`；或 Agent 工具 `inspect` 返回 `dependencies`。
- 启动：同一 Docker network，容器名 `codesentry-dep-<scan>-<kind>`，不发布宿主端口；MySQL 初始化 `MYSQL_DATABASE`，依赖健康检查后再启动目标。
- env 注入：
  - MySQL：`MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_USERNAME`、`MYSQL_PASSWORD`、`MYSQL_DATABASE`
  - Redis：`REDIS_HOST`、`REDIS_PORT`
  - PostgreSQL：`POSTGRES_HOST`、`POSTGRES_PORT`、`POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`
- 镜像缺失：
  - `pull=never` → 记 degraded，明确原因；
  - `missing/always` → 拉取；失败 → degraded，不影响构建结果；
  - `allow_remote_images=false` 时不得拉取远程。
- 清理：`cleanup_scan` 同时删除依赖容器/网络；`DeployResult.meta.dependencies` 记录状态。
- Agent 工具：`detect_dependencies`、`ensure_dependency(kind)`，由 Agent 决策；无 LLM 时确定性 fallback 自动执行。
- 验收：单测 mock Docker；kvf 真实尝试：MySQL/Redis 启动成功则目标 ready，否则 degraded 且记录具体依赖失败。

## 2. JS/TS 匿名回调

- `GenericExtractor` 对 JS/TS 的匿名 arrow/function expression 生成 `function:<path>#anon@L<line>` 节点，`qualified_name=anon@L<line>`，记录 params/sources/sinks。
- `_routes` 的 `owner(line)` 能匹配匿名函数（start/end 包含路由行或路由后一行）。
- 同一匿名回调只生成一次（按 key 去重）。
- 验收：JS fixture `app.get('/run',(req,res)=>{ exec(req.query.cmd) })` 产生 endpoint→function `routes_to`、function→sink `contains`、CodeQL source→sink dataflow；路径 feasibility=proven。

## 3. CodeQL 自动安装

- 配置：
  - `codeql_auto_install: bool = False`
  - `codeql_version: str = "2.27.2"`
  - `codeql_license_ack: bool = False`
  - `codeql_install_dir: str = ""`（默认 `<work_dir>/tools/codeql`）
  - `codeql_sha256: str = ""`（可选；为空则只安装固定官方 URL，记录未校验警告）
- API：
  - `POST /api/engines/codeql/install`，body `{version, license_ack}`；admin。
  - `GET /api/engines/codeql/install/status`。
- 下载 URL 仅允许 `github.com/github/codeql-action/releases/download/codeql-bundle-v<version>/...`；禁止任意 URL。
- 安全解压：只接受 `.tar.gz`/`.zip`，拒绝绝对路径/`..`/链接；安装后验证 `codeql version`。
- 自动触发：`run_scan_agent` 在 OSS + CodeQL 不可用 + `auto_install` + `license_ack` 时调用安装；失败降级其他引擎。
- 验收：URL 白名单、拒绝未 ack、mock 下载/解压/版本校验；真实安装可作为 live 验证。

## 4. 自动修复建议

- 新 `POST /api/findings/{finding_id}/fix`：输入 finding + 源码切片 + 图路径，LLM 输出：
  `{"summary":"...","patch":"--- a/...\\n+++ b/...\\n@@ ...","tests":["..."],"risk":"..."}`
- 只返回/展示，**不写源码**；可选保存到 `findings.fix_patch/fix_summary`（迁移列）。
- 安全检查：patch 必须只包含 unified diff 文本；拒绝 shell、下载执行、删除整文件等危险模式。
- UI：Finding 抽屉新增“生成修复建议”按钮与 patch 展示。
- 验收：mock LLM 单测；非法 finding 404；无 LLM 返回 503；不修改工作区文件。

## 5. 远程 PoC 目标（受限）

- 表 `poc_targets(id,name,base_url,allowed_hosts,expires_at,enabled,created_at)`。
- 配置 `poc_remote_enabled=False`；只有显式开启 + 目标未过期 + host 匹配 allowed_hosts 才允许。
- 默认拒绝私网/loopback/link-local；`poc_remote_allow_private=False` 时不得登记私网。
- API：CRUD + `POST /api/poc-targets/{id}/probe`（只读 HEAD/GET `/`，超时 5s，不执行 finding payload）。
- `POC_RUN=target` 仅对已授权目标的 **canary 回调请求**执行；不轰炸、不并发、不持久化。
- 验收：未开启 403；过期 403；host 不匹配 400；probe 只读；单测 mock httpx。

## 6. 交互式/反弹 shell

明确不实现。任何 shell 执行仍受：
- 固定 argv / 无 `/bin/sh -i`、`/dev/tcp`、`nc -e`、`bash -i`；
- 30-60s 超时；
- 容器内无宿主 socket；
- 输出截断与审计。
