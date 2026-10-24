# CodeQL 引擎接入 · Code Review 第 2 轮（可靠性/安全/性能）

## 发现与修复

| # | 等级 | 问题 | 修复 |
|---|---|---|---|
| 1 | 必须 | 解析 app_settings 失败可能抛异常 | `_setting` 全捕获返回空，回退 env |
| 2 | 必须 | `build_command` 在 none 模式误执行 | 仅 manual + 非空时传 `--command` |
| 3 | 必须 | 大仓库指纹计算过慢 | 跳过 `.git/node_modules/target/build/dist`；只取路径+mtime+size |
| 4 | 必须 | 超时仍沿用旧 3600 | 默认 1800，可配置 |
| 5 | 建议 | cache 命中但源码变化会用旧 DB | 指纹包含 mtime/size，变化即新 DB |
| 6 | 建议 | 找不到 packs 时错误不明确 | suite/search_path 原样记录在失败 reason |
| 7 | 建议 | 健康检查仍用 `which("codeql")` | 使用解析后的本机 binary |

## 安全

- 不下载 CodeQL/packs；只使用本机。
- `build_command` 只作为用户显式配置，默认 none；执行在目标仓库 cwd。
- OSS Gate 不变，闭源禁止 CodeQL。
- SARIF 解析不执行源码。

## 性能

- DB cache 命中跳过 create；大仓库指纹排除构建目录。
- 分析超时 1800s；失败降级。

## 验证

- 真实 Java 小样：status ok，SARIF 生成。
- 303 passed；ruff/mypy 绿。

## 结论

P1 引擎能力通过。P2 WebUI 接入待后续迭代。
