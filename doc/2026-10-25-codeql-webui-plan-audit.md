# CodeQL WebUI 接入 · Plan 审计

- 对象：`doc/2026-10-25-codeql-webui-plan.md`
- 结论：**通过（3 项内联修复，3 项实现注意）**

## 已修复

| # | 问题 | 修复 |
|---|---|---|
| 1 | 设置 GET 返回空值会让用户误以为丢失 | UI 显示“自动探测”，GET 保留空值语义 |
| 2 | test 接口返回结构未定义 | 统一 `{ok,binary,version,languages,packs,error}` |
| 3 | 扫描详情 artifact 解析可能很大 | 只读 preview/最新 graph_delta，限制长度 |

## 实现注意

1. `resolve languages` 输出多行；解析为语言名列表，失败不影响 version。
2. Settings 现有表单按 group 组织，新增 codeql 时不要复用 LLM 密钥逻辑。
3. Overview 的 `engines` 仍是字符串；新 `engine_details` 可选，旧后端也能渲染。

## 风险

- CodeQL test 执行外部 binary：仅 admin，路径来自配置；不做 shell。
- build_command UI 警告不足：manual 时显示红色提示。

## 验收映射

- Task 1/2 单测；Task 3/4/5 前端 build + 手动路由冒烟。
- 全量 303+ 测试。
