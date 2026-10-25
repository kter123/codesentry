# 剩余需求 Code Review 第 2 轮（安全/可靠性）

- 日期：2026-10-25
- 范围：认证/密钥、通知、项目/调度、配置导入导出、部署、生命周期、前端

| # | 等级 | 问题 | 修复/确认 |
|---|---|---|---|
| 1 | 必须 | webhook secret 新渠道仍可能明文落库 | `create_webhook` 统一 `enc:<fernet>`；读取兼容旧明文；列表/导出不返回 secret |
| 2 | 必须 | webhook 自定义 headers 可能含 Authorization/Token，列表会泄露 | `_public_headers` 对 authorization/token/secret/api-key/password 值替换 `***` |
| 3 | 必须 | 配置导出可能包含 `*_api_key`、smtp password、codeql build_command | 导出过滤 `api_key/password/secret` 与 `codeql_build_command`；导入强制忽略敏感键 |
| 4 | 必须 | project.repo_path 可指向宿主任意目录 | 创建/更新/运行均 `validate_repo_path`，必须位于 work 根内且存在 |
| 5 | 必须 | git_url 可指向 localhost/私网 | 复用 HTTPS + DNS 私网校验；scheduler 克隆前再次校验 |
| 6 | 必须 | scheduler 多 worker 重复扫描 | `claim_due_schedules` 行锁 + 原子更新 next_run_at；按 due 时间认领 |
| 7 | 必须 | `deploy_image_pull=never` 仍可能 pull | `ensure_image` 对 recipe 镜像强制策略；Docker build `pull=always` 才拉 |
| 8 | 必须 | 路径 PoC 可能跨扫描读取 audit_paths | `_path_context` 固定 `WHERE scan_id=%s AND id=%s` |
| 9 | 必须 | 生命周期 purge 可能删除其他扫描共享的 repo job | 删除前统计其他 scans 引用同一 job，存在则保留 |
| 10 | 重要 | 目标镜像清理误删用户镜像 | 仅 `codesentry-target-*` 且无容器引用；默认 `clean_images=false` |
| 11 | 重要 | `delete_scan` 只删子表，不删 audit_paths/rounds | 保留清理脚本/维护任务补审计表；删除 UI 仍按用户显式操作 |
| 12 | 重要 | 浏览器 smoke 不能用 HTTP 200 冒充渲染 | Playwright 检查 `#app/#root` 子节点、标题、抽屉内容、console error；Safari 失败输出 BLOCKED |
| 13 | 确认 | PoC 危险 payload 过滤 | `rm -rf`/sudo/反弹 shell/管道执行仍拒绝；POC_RUN 默认 off |
| 14 | 确认 | Docker 端口 | host 模式仍只绑 `127.0.0.1`；internal 不发布端口 |
| 15 | 确认 | 多租户 | 未引入；RBAC 路径已把 projects/schedules/agent-presets 写操作归 admin |

## 认证/权限

- `/api/projects`、`/api/schedules`、`/api/agent-presets` 加入 `ADMIN_PREFIXES`：
  - GET → analyst/viewer；
  - 写操作 → admin。
- `/api/config/export|import` 已在 `/api/config` admin 前缀内。
- `/api/webhooks` 已在 admin 前缀内；通知测试接口同前缀。

## 可靠性

- 通知投递 10s 超时、最多 2 次重试；单渠道失败不阻塞扫描。
- SMTP 缺配置返回 `{ok:false}`，不抛到扫描链路。
- scheduler 单计划失败写 `last_error`，不终止循环。
- maintenance 默认不清理镜像；CodeQL cache/orphan 仅按 mtime 过期删除。

## 结论

安全阻断项已修复；没有发现新的硬编码密钥或未授权远程执行路径。已知限制见 implementation 文档。
