# CodeQL 接入 · Spec 审计

- 对象：`doc/2026-10-25-codeql-integration-spec.md`
- 结论：**通过（5 项内联修复，4 项转 Plan）**
- 优先级确认：P1 引擎能力先做，P2 WebUI 后做

## 已修复

| # | 问题 | 修复 |
|---|---|---|
| 1 | 未明确 P1/P2，容易先做 UI | 增加优先级章节；本次验收只覆盖引擎能力 |
| 2 | suite 参数缺 pack 前缀/搜索路径 | 配置默认按 `codeql/<lang>-queries:codeql-suites/...` 解析 |
| 3 | Java 无构建工具时 autobuild 失败 | 默认 `build-mode=none`，manual 才执行 build_command |
| 4 | WebUI 状态接口只返回路径 | P2 明确返回 `{found,version,search_path,packs}` |
| 5 | 未定义失败降级 | `unavailable/crashed` 不阻塞 Semgrep/Joern/报告 |

## 转 Plan

1. CodeQL 配置解析优先级（app_settings → env → PATH → `.codesentry/tools`）。
2. 数据库缓存 key 与 `--overwrite` 规则。
3. SARIF 输出路径与 scan 的 codeql_graph 调用。
4. 合成 Java 仓库的引擎测试（不依赖 WebUI）。

## 风险

| 风险 | 缓解 |
|---|---|
| packs 版本/依赖缺失 | 启动时 `resolve packs` 检查；错误写明包名 |
| build-mode=none 缺依赖信息 | 报告标注；必要时用户改 manual |
| build_command 注入 | 只在目标仓库执行；默认 none；UI 提示 |
| CodeQL 慢/超时 | 1800s 默认；失败降级 |

## 验收可行性

- 本机已实测 CLI 2.27.2 + java packs + `build-mode=none` 成功。
- 引擎层可单测配置解析、命令构造、SARIF 解析；真实 Java 小样跑一次。
