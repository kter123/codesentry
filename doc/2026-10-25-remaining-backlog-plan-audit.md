# 剩余需求 Plan 审计

- 日期：2026-10-25
- 审计对象：`doc/2026-10-25-remaining-backlog-plan.md`
- 结论：**通过，需补 9 项执行细节**。不补会导致权限、并发或泄露问题。

## 必须补充

| # | 问题 | 修订 |
|---|---|---|
| 1 | 新 API `/api/projects`、`/api/schedules`、`/api/agent-presets` 未加入角色策略，默认写操作只需 viewer | 在 `control/auth.py` 的 `ADMIN_PREFIXES` 加这三个前缀；GET 仍 analyst/viewer；写 admin。 |
| 2 | scheduler 默认启动会干扰测试/多 worker | 新增 `scheduler_enabled: bool = True`，测试 fixture 设 false；startup 只在 enabled 时启动；`scheduler_interval_s=30`。 |
| 3 | cron 未定义时区 | 统一 UTC；`cron_next` 接受 aware datetime，返回 UTC。 |
| 4 | config import `replace` 语义未定义 | 只对 prompts/agent_configs/agent_presets/skills/templates/webhooks 做 upsert；不删除 llm_profiles/users/scans；返回每类 counts。 |
| 5 | email/smtp password 解密规则未覆盖 | `_read_setting`/`_mask` 对 `*_password`、`*_secret` 也加密/掩码；设置 group `notifications` 加入 whitelist。 |
| 6 | webhook secret 迁移未定义 | `_decrypt_secret`：`enc:` 前缀解密；无前缀按旧明文；创建/更新一律加密。`dispatch` 只用解密后的 secret 签名，不写日志。 |
| 7 | CodeQL 多语言结果排序/重复 engine 无法区分 | spec `__name__` 用 `run_codeql_<lang>`，`EngineResult.lang` 记录；异常兜底按 `run_codeql` 前缀识别。 |
| 8 | 路径 PoC 查 `audit_paths` 未校验 scan_id | `_path_context(scan_id, path_id)` 必须 `WHERE scan_id=%s AND id=%s`；不存在返回空，不跨扫描。 |
| 9 | 前端新增页面/对话框缺类型定义 | 为 Projects/Schedule/PathDetail/Preset 增加 `api/types.ts` 接口；`vue-tsc`/build 必须通过。 |

## 建议补充

- `retention.purge_scans` 用 `DELETE ... WHERE scan_id` 顺序：audit_paths/audit_rounds/review_comments/agent_artifacts/findings/node_runs/budget/usage → scans；任何一步失败返回 0 并记录。
- `cleanup_target_images` 只删 `codesentry-target-` 且 `containers` 为空；失败不影响主流程。
- `ui_smoke_safari.py` 需要启动 `uvicorn`，等待 `/api/health` 200；退出杀进程；认证开启时用 admin 登录；默认本地模式直接访问。
- `validate_codeql_fullchain.py` 用 `CODESENTRY_LLM_ENABLED=false` + `CODESENTRY_DEPLOY_ENABLED=false`，避免 CI 外部依赖；只验证 CodeQL/图/路径/报告。
- 所有新 DB 操作使用 `ensure_control_schema()`，避免旧库缺列。

## 任务顺序复核

依赖关系正确：任务 1（DDL/统计）→ 2（CodeQL）→ 3（PoC）→ 4（UI/API）→ 5（Deploy）→ 6-14（运营面）→ 15（验证）。
建议把任务 6/7/8/10 的 DDL 合并到任务 1 一次执行，减少反复迁移；实现仍按任务拆分。

## 安全复核

- secret 不返回、不导出、不日志。
- project repo_path 限 work 根；git_url HTTPS + 私网校验。
- webhook URL 仅 admin 可配；请求超时 10s，重试 2 次。
- Safari smoke 不注入真实凭据；本地模式无 token。
- CodeQL/PoC 仍受 OSS Gate / POC_RUN 控制。

## 结论

按上述 9 项补充后开始实现；每完成一个任务运行对应测试并 commit，最后统一两轮 code review。
