# CodeQL WebUI 接入 · Code Review 第 1 轮（正确性）

| # | 等级 | 问题 | 修复 |
|---|---|---|---|
| 1 | 必须 | settings 只允许 llm/embedding，codeql 会 404 | 扩展分组与 key 白名单 |
| 2 | 必须 | codeql GET 空值无默认，用户误以为配置丢失 | 空值语义=自动探测，UI 显示占位与状态 |
| 3 | 必须 | status/test 未返回 suite/build_mode | 返回完整解析结果 |
| 4 | 建议 | packs 列表只显示顶层 `codeql` | 解析 `search_path/codeql/*` 子目录 |
| 5 | 建议 | Overview 旧前端只认字符串 | 保留 `engines`，新增 `engine_details` |

## 验证

- settings PUT/GET 回读一致。
- 真实 status：2.27.2、java/python 等语言、packs。
- 前端 build 通过。

## 遗留

- 扫描详情仅展示 dataflow 数，未做 SARIF 下载链接。
