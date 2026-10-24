# CodeQL 引擎接入 · Code Review 第 1 轮（正确性）

## 发现与修复

| # | 等级 | 问题 | 修复 |
|---|---|---|---|
| 1 | 必须 | `settings.codeql_bin` 默认 `"codeql"` 会覆盖自动探测 | 显式值仅在非 `"codeql"` 时优先，否则使用解析出的本机 binary |
| 2 | 必须 | suite 缺 pack 前缀，analyze 找不到 | 默认 `codeql/<lang>-queries:codeql-suites/...`，支持显式配置 |
| 3 | 必须 | 未传 `--search-path`，本地 packs 不可见 | create/analyze 均传 search_path |
| 4 | 必须 | Java 无构建工具时 autobuild 失败 | 默认 `build-mode=none`；manual 才执行 command |
| 5 | 必须 | DB 缓存名仅 repo 名，跨仓库冲突 | 改为 repo 内容指纹 + lang |
| 6 | 必须 | SARIF 路径与 codeql_graph 读取不一致 | 固定 `work_dir/codeql-<lang>.sarif` |

## 验证

- 真实 CodeQL：status ok、SARIF 存在。
- 命令构造单测：build-mode/search-path/suite/overwrite。
- 全量 303 passed。

## 遗留

- 小样 findings=0，需真实 Web 入口样例验证规则命中。
- P2 WebUI 未做。
