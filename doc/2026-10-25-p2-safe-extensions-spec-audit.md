# P2 安全扩展 Spec 审计

- 日期：2026-10-25
- 对象：`doc/2026-10-25-p2-safe-extensions-spec.md`
- 结论：**有条件通过**；以下 10 项在 plan 中落实。

## 阻断项

| # | 问题 | 修订 |
|---|---|---|
| A1 | 依赖容器若加入内部网络，目标与依赖可用 alias 通信；若 target 在 host 网络则依赖不可达 | 依赖与目标统一使用同一 bridge network + alias；host 模式仅发布目标端口，依赖不发布。 |
| A2 | MySQL 镜像拉取可能绕过 `deploy_image_allow_remote` | 依赖镜像也必须走 `ensure_image` + `allow_remote`；`never` 缺失直接 degraded。 |
| A3 | CodeQL 下载 URL 必须固定官方 host，防止 SSRF/任意包 | URL 白名单 `github.com/github/codeql-action/releases/download/`；解析后 host 必须匹配；禁止重定向到私网（httpx follow_redirects=False 或校验最终 URL）。 |
| A4 | 自动安装不能绕过许可 Gate | 必须 `license_ack=true` + OSS Gate；下载前写 config_audit；失败降级。 |
| A5 | 自动修复 patch 可能包含危险命令/整文件删除 | 只接受 unified diff；拒绝 `rm -rf`、`/dev/tcp`、`curl|sh`、`sudo`；不写源码。 |
| A6 | 远程 target 默认不能允许私网 | `poc_remote_allow_private=false`；DNS 解析后所有 IP 都校验；重定向目标也校验。 |
| A7 | 远程 probe/PoC 可能被滥用为扫描器 | 仅单 URL、单请求、5s 超时、无并发、无 payload 字典；只允许 GET/HEAD。 |
| A8 | 反弹 shell 功能明确不做 | 代码中增加静态拒绝（已有 DANGEROUS_PATTERNS）；新增测试确保 `/dev/tcp`、`bash -i`、`nc -e` 均拒绝。 |

## 重要项

| # | 问题 | 修订 |
|---|---|---|
| B1 | 依赖健康检查 MySQL 首次初始化慢 | 最多 `deploy_dependency_timeout_s`，轮询 `mysqladmin ping` 或 TCP；超时 degraded 但不阻塞构建。 |
| B2 | 依赖容器/网络清理 | `cleanup_scan` 删除 `codesentry-dep-*` + network；`run_maintenance` 可清理孤立依赖容器。 |
| B3 | 匿名函数重复节点 | key 用 `anon@L<line>`，抽取前查 result 节点 key。 |
| B4 | 匿名函数 `owner` 只按行包含 | 同时匹配“路由行后一行内开始的函数”，避免箭头函数换行。 |
| B5 | CodeQL 安装包 SHA | 若配置 sha256 必须匹配；未配置记录 warning，不允许静默忽略校验错误。 |
| B6 | 自动修复需要审计 | 生成/查看 patch 都写 config_audit 或 finding tool_trace；不写源码。 |
| B7 | 远程 target API 权限 | 加入 `ADMIN_PREFIXES`；probe 也仅 admin。 |

## 结论

安全边界清晰：不做反弹/交互 shell，不做远程利用，只做授权目标只读探测。按 A1-A8、B1-B7 进入 plan。
