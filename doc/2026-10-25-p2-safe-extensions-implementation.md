# P2 安全扩展实现记录

- 日期：2026-10-25
- 规格：`doc/2026-10-25-p2-safe-extensions-spec.md`（含审计）
- 计划：`doc/2026-10-25-p2-safe-extensions-plan.md`

## 已实现

| 能力 | 文件 | 说明 |
|---|---|---|
| 部署 Agent 自主依赖 | `sandbox/dependencies.py`、`sandbox/deploy.py`、`agents/deploy_agent.py` | 自动识别 MySQL/Redis/PostgreSQL；同 network + alias；env 注入；策略拉镜像；失败 degraded |
| JS/TS 匿名回调图节点 | `rag/extractors/generic.py` | 生成 `function:<path>#anon@L<n>`；路由 `routes_to`；路径可 proven |
| CodeQL 预授权自动安装 | `control/engine_install.py`、`engines/scan.py`、`web/control_api.py`、Settings UI | 版本/许可/SHA/目录；官方 URL 白名单；安全解压；扫描前自动安装 |
| 修复建议 | `agents/fix_agent.py`、`web/control_api.py`、ScanDetail UI | 只产 unified diff；危险模式拒绝；不写源码 |
| 远程 PoC target | `control/poc_targets.py`、`web/control_api.py`、Settings UI | 目标登记/过期/host 白名单；只读 GET/HEAD 探测；默认关闭 |
| 交互式/反弹 shell | — | **明确不实现**；危险 payload 静态拒绝 |

## 部署依赖行为

- 配置：
  - `CODESENTRY_DEPLOY_AUTO_DEPENDENCIES=true`
  - `CODESENTRY_DEPLOY_DEPENDENCY_MYSQL_IMAGE`
  - `CODESENTRY_DEPLOY_DEPENDENCY_REDIS_IMAGE`
  - `CODESENTRY_DEPLOY_DEPENDENCY_POSTGRES_IMAGE`
  - `CODESENTRY_DEPLOY_DEPENDENCY_TIMEOUT_S=90`
- 流程：目标启动前创建 bridge network；按需启动 `codesentry-dep-<scan>-<kind>`；health 通过后注入 env；目标用同一 network。
- 镜像策略：`never` 只允许本地；`missing/always` 走 `ensure_image`；`allow_remote=false` 时不拉远程。
- 清理：`cleanup_scan` 删除目标、依赖容器和网络。

## JS 匿名回调验证

- 抽取结果：`route:js_cmd.js#GET:/run → function:js_cmd.js#anon@L5`，`anon → sink`。
- CodeQL 同 line source/sink 现在按 column 区分，能生成 `function → sink` dataflow。
- 实跑 JS 全链路：出现 `entry=function:js_cmd.js#anon@L5` 的 `proven` 路径；CWE-78 命令注入 finding 落库；报告生成。
- 修复路径候选跨批次被覆盖的问题：`run_audit_collect` 合并历史 candidate，保留早期命令注入候选。
- 单测：`tests/test_js_anon.py`。

## CodeQL 自动安装

- API：
  - `GET /api/engines/codeql/install/status`
  - `POST /api/engines/codeql/install` body `{version, license_ack, sha256}`
- 扫描自动：OSS + CodeQL 不可用 + `codeql_auto_install=true` + `codeql_license_ack=true`。
- 安全：仅 `github.com/github/codeql-action/releases/download/`；不跟随重定向；拒绝绝对路径/`..`/链接；SHA 可选；安装后 `codeql version` 验证。
- 单测：`tests/test_codeql_install.py`（许可、URL、SHA、成功安装）。
- 真实下载未执行（需要许可确认与网络；代码路径已覆盖）。

## 修复建议

- `POST /api/findings/{id}/fix`：读取 finding + 源码切片，调用 AuditAgent 绑定的 LLM。
- 只写 `findings.fix_patch/fix_summary/fix_tests`，**不修改工作区源码**。
- patch 必须 unified diff；拒绝 shell/rm -rf/反弹 shell/管道执行。
- UI：Finding 抽屉“生成修复建议”，展示 patch 与测试建议。

## 远程目标

- 表 `poc_targets`；`POC_REMOTE_ENABLED=false` 默认。
- 只允许 HTTPS、host 白名单、未过期、非私网（除非显式 `POC_REMOTE_ALLOW_PRIVATE=true`）。
- `POST /api/poc-targets/{id}/probe`：单次 GET `/`，5s 超时，不跟随重定向，不执行 finding payload。
- UI：设置页开关、目标表、探测/删除。
- 不做远程利用、批量扫描、持久化。

## 验证

- `pytest`：372+（本轮新增依赖/CodeQL 安装/JS/修复/远程目标测试）
- `ruff`/`mypy`：通过
- 前端 build：通过
- 真实 kvf 依赖启动：尝试被安全分类器拦截（Production Deploy），未执行；MySQL 镜像已从 daocloud 镜像拉取到本地，代码/单测已覆盖编排逻辑。

## 明确边界

- 不实现交互式 shell、反弹 shell、远程任意利用、自动修改源码。
- 远程 target 只用于已授权环境的只读健康探测。
