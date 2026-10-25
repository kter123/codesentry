# Fusion Phase 1 实现记录（可观测性 + Harness MVP）

- 日期：2026-10-25
- 计划：`doc/2026-10-25-fusion-phase1-plan.md`
- 设计：`doc/2026-10-25-deepaudit-fusion-spec.md`

## 已实现

### 1. 路径 finding 增量落库

- DDL 增加 `findings_scan_path_uidx`（`scan_id,path_id` 唯一，`path_id IS NOT NULL`）。
- 启动时先清理历史重复 `findings`，避免索引创建失败。
- `run_audit_path` 完成 `finding` 时立即 upsert `findings`，`verdict='candidate'`。
- runner 最终落库改为同 key upsert，不再重复插入。
- 效果：扫描运行中 `/api/scans/{id}/findings` 就能看到 Agent 结果。

### 2. 超时/失败状态与进度

- `need_more` 且 reason 含“超时” → `audit_paths.status=timeout`。
- reason 含“审计失败/失败：” → `status=error`。
- `coverage` 增加 `done/timeout/error`。
- 扫描详情路径 tab 显示“已审 / 待审 / 超时”。
- Findings tab 在 running 时显示“Agent 实时结果”。

### 3. Harness MVP

- `control/harness.py`：
  - LLM 生成 JSON：language/code/summary/payloads。
  - 约定输出 `HARNESS_VERIFIED` / `HARNESS_NOT_TRIGGERED`。
  - Docker 沙箱：默认 `network=none`、read_only、cap_drop=ALL、no-new-privileges、512MB、90s。
  - 结果写 `verification_runs`，并更新 finding verdict。
- API：
  - `POST /api/findings/{id}/verify`
  - `GET /api/scans/{id}/verifications`
- UI：Finding 抽屉新增“Harness 验证”，展示 verdict/summary/stdout/stderr。
- 配置：
  - `CODESENTRY_HARNESS_IMAGE`
  - `CODESENTRY_HARNESS_TIMEOUT_S`
  - `CODESENTRY_HARNESS_ALLOW_NETWORK=false`
  - `CODESENTRY_HARNESS_PULL_POLICY=missing`

## 真实验证

- 单测：`378 passed, 2 skipped, 1 xfailed`。
- ruff/mypy：通过。
- 前端 build：通过。
- 真实 Harness（本地镜像 `docker.m.daocloud.io/library/python:3.12-slim`）：
  - 输入 `print('HARNESS_VERIFIED')`
  - 结果 `status=ok, verdict=verified, exit_code=0, duration_ms=361`
- 真实 kvf/扫描验证：上一轮 scan 1610 已停止；待重新扫描 JVWA 验证 live findings。

## 已知限制

- Harness 镜像默认 `python:3.12-slim`，Java/JS/PHP/Go/Ruby 需要包含对应运行时的镜像；可通过 `HARNESS_IMAGE` 配置。
- 未配置 LLM 时 Harness 返回 503，不会伪造 verified。
- Harness 代码由 LLM 生成，仍可能环境失败；结果分类 `environment_error → plausible`，不直接丢弃。
- 本轮未实现 Supervisor 动态调度与 Agent 工作台；属于 Phase 2。
