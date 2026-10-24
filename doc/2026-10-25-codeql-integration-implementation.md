# CodeQL 引擎接入 · 实现记录（P1）

- 日期：2026-10-25
- 规格：`doc/2026-10-25-codeql-integration-spec.md`
- 计划：`doc/2026-10-25-codeql-integration-plan.md`
- 范围：**P1 引擎能力**；WebUI 为 P2，暂未实现

## 环境勘察

| 项 | 结果 |
|---|---|
| CLI | `/Users/kking/.codesentry/tools/codeql/codeql`，2.27.2 |
| packs | `/Users/kking/.codeql/packages`，java/python/javascript/go/cpp/csharp/ruby |
| Java 建库 | `--build-mode=none` 离线成功 |
| 分析 | `codeql/java-queries:codeql-suites/java-security-extended.qls` 成功，SARIF 生成 |
| 小样 | `Vuln.run(Runtime.exec)`：status ok，findings 0（规则需要真实入口/数据源） |

## 已实现

| 能力 | 文件 |
|---|---|
| 配置解析（DB → env → PATH → `~/.codesentry/tools`） | `control/engine_config.py` |
| 配置字段 | `config.py`：search_path/suite/build_mode/build_command/timeout/cache |
| 引擎命令 | `engines/codeql.py`：build-mode、search-path、suite、DB cache、timeout |
| SARIF 路径 | `work_dir/codeql-<lang>.sarif`（scan 的 codeql_graph 对齐） |
| 健康检查 | `/api/health` 的 CodeQL 使用解析后的 binary |
| 单测 | `test_codeql_config.py`、`test_codeql_engine.py` |

## 关键行为

- binary 优先级：显式值（非 `"codeql"`）→ 解析出的本机路径 → PATH。
- suite 默认：`codeql/<lang>-queries:codeql-suites/<lang>-security-extended.qls`。
- `build_mode=none` 默认；`manual` 才把 `--command` 传给 `database create`。
- cache=true：按 repo 内容指纹复用 DB，命中跳过 create；cache=false 带 `--overwrite`。
- 失败：binary/packs 缺失 `unavailable`；退出码非 0 `crashed`，均不阻塞其他引擎。

## 验证

- 真实 CodeQL：status ok，SARIF 文件存在。
- 单测：命令包含 `--build-mode=none`、`--search-path`、suite；无 binary 时 unavailable。
- 全量：**303 passed, 2 skipped, 1 xfailed**；ruff/mypy 绿。

## P2 待做（WebUI）

- 设置页 CodeQL 配置面板（binary/search_path/suite/build_mode/build_command）。
- `/api/settings/codeql`、`POST /api/engines/codeql/test`。
- 健康状态返回版本/packs；扫描详情展示 SARIF/dataflow 统计。
