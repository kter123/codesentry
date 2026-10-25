# CodeQL WebUI / 系统接入 · 实现记录（P2）

- 日期：2026-10-25
- 规格：`doc/2026-10-25-codeql-webui-spec.md`
- 计划：`doc/2026-10-25-codeql-webui-plan.md`

## 已实现

| 能力 | 文件 |
|---|---|
| `codeql` settings 分组（7 个 key） | `web/server.py` |
| `GET/PUT /api/settings/codeql` | `web/server.py` |
| `GET /api/engines/codeql/status` | `web/control_api.py` |
| `POST /api/engines/codeql/test` | `web/control_api.py` |
| `/api/health` 新增 `engine_details.codeql` | `web/control_api.py` |
| CodeQL 解析状态 | `control/engine_config.py::codeql_status` |
| 设置页「CodeQL 引擎」面板 | `SettingsView.vue` |
| 概览显示 CodeQL 版本 | `OverviewView.vue` |
| 扫描详情 CodeQL dataflow 标签 | `ScanDetailView.vue` |
| API 单测 | `tests/test_codeql_api.py` |

## 真实状态（本机）

```
found: true
version: CodeQL command-line toolchain release 2.27.2.
binary: /Users/kking/.codesentry/tools/codeql/codeql
search_path: /Users/kking/.codeql/packages
suite: codeql/java-queries:codeql-suites/java-security-extended.qls
build_mode: none
languages: go/python/rust/java/html/xml/...
packs: java/python/javascript/go/cpp/csharp/ruby
```

## 行为

- 设置页空值表示自动探测；保存后无需重启，扫描时 `resolve_codeql_config` 重新读取 app_settings。
- 探测只执行 `version` / `resolve languages`；不执行 build_command。
- `build_command` 仅在 `build_mode=manual` 时可编辑，扫描时才传给 `database create`。
- 概览 `engines` 字符串保持兼容；新增 `engine_details` 对象展示版本。
- 扫描详情从 scan artifact 的 `graph_delta.engine_graph.codeql` 读取 dataflow 数；无 CodeQL 时隐藏。

## 真实能力验证

- `CmdServlet(HttpServletRequest#getParameter -> Runtime.exec)`：
  - CodeQL status `ok`，**1 条 finding**：`java/command-line-injection`，CWE-78，`CmdServlet.java:8`。
  - 修复了 SARIF 解析的 `_sev` 未初始化 bug，并补 CWE 从 rule properties 读取。
- WebUI status：2.27.2、binary、search_path、suite、build_mode、语言与 packs。

## 验证

- `test_codeql_api.py`：settings 回读、status/test、health。
- 真实 status/test：2.27.2 + 语言列表。
- 全量：**306 passed, 2 skipped, 1 xfailed**；ruff/mypy 绿；前端 build 通过。
