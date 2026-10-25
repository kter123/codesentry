# CodeQL WebUI / 系统接入 · P2 设计规格

- 日期：2026-10-25
- 前置：P1 引擎能力已完成（`2026-10-25-codeql-integration-*`）
- 状态：待 spec 审计

## 0. 目标

把已可用的 CodeQL 引擎暴露到控制台：

1. 全局设置页可配置 CodeQL（binary/search_path/suite/build_mode/build_command/timeout/cache）。
2. 可一键“探测”本机 CodeQL：版本、packs、语言。
3. 健康检查/总览显示 CodeQL 是否可用、版本。
4. 配置保存到 `app_settings`，引擎执行时实时读取。
5. 扫描详情能看到 CodeQL 是否运行及 SARIF/dataflow 统计（最小展示）。

## 1. 配置项（app_settings key）

`codeql_bin`、`codeql_search_path`、`codeql_suite`、`codeql_build_mode`、
`codeql_build_command`、`codeql_timeout_s`、`codeql_db_cache`。

- 空值 = 使用自动探测/env 默认。
- 无密钥字段，不需要加密。

## 2. API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/settings/codeql` | 返回当前配置（空值表示自动） |
| PUT | `/api/settings/codeql` | 保存；只允许上表 key |
| POST | `/api/engines/codeql/test` | 本地探测：`version`、`resolve languages`、packs 目录 |
| GET | `/api/engines/codeql/status` | 解析后的 binary/search_path/suite/build_mode/version/found |

- 所有写操作走 admin 权限（与现有 settings 一致）。
- `test` 不执行 build_command，只跑 `version` 与 `resolve languages`。
- 超时 10s；失败返回 `{ok:false,error}`，不抛 500。

## 3. WebUI

### 3.1 全局设置新增「CodeQL 引擎」面板

字段：

- Binary（placeholder：自动探测 `~/.codesentry/tools/codeql/codeql`）
- Search path（packs）
- Suite（按语言模板，支持 `{lang}`）
- Build mode（none/autobuild/manual）
- Build command（仅 manual 显示/启用）
- Timeout（秒）
- DB cache（开关）

按钮：保存、探测。
探测结果：版本、binary、packs 路径、语言列表、错误。

### 3.2 概览引擎状态

- `engine_details.codeql`：`{found, version, search_path, suite, build_mode}`。
- 概览卡片显示 `codeql：已安装 2.27.2` 或 `未检测到`。
- 保留 `engines.codeql` 字符串以兼容现有前端。

### 3.3 扫描详情

- 新增「引擎」小节/卡片：CodeQL 是否运行、SARIF 文件、dataflow 边数。
- 数据来自 scan artifacts 的 `graph_delta.engine_graph.codeql`；无则不显示。
- 最小实现：读取 artifacts 中 graph_delta，不新增表。

## 4. 行为

- 保存后无需重启；`resolve_codeql_config()` 每次扫描重新读取 app_settings。
- 探测失败不影响保存。
- CodeQL 不可用时设置页显示明确错误；扫描仍降级到其他引擎。

## 5. 安全

- 设置写接口仅 admin；读取不含密钥（CodeQL 无密钥）。
- `test` 只执行配置的 CodeQL binary 的 `version` / `resolve languages`，不执行 build_command。
- build_command 仅保存文本，扫描时 manual 才执行；UI 明确提示“会在目标仓库执行”。
- 不允许通过 API 读取任意文件；packs 只列目录名。

## 6. 验收

1. Settings 页保存 CodeQL 配置后，`GET /api/settings/codeql` 回读一致。
2. `POST /api/engines/codeql/test` 返回 2.27.2、packs 路径、语言列表。
3. `/api/engines/codeql/status` 返回自动探测到的 binary/suite/build_mode。
4. Overview 显示 CodeQL 版本；未安装时显示未检测到。
5. 全量测试、ruff/mypy、前端 build 通过。
