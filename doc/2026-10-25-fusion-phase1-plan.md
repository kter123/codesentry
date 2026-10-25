# Fusion Phase 1 实施计划（可靠性与 Harness MVP）

**目标：** 先让 Agent 审计结果“运行中可见、失败可解释”，再落地 Harness 验证最小闭环。

## 任务 1：路径 finding 增量落库

- DDL：
  - dedupe 旧 findings；
  - `CREATE UNIQUE INDEX findings_scan_path_uidx ON findings(scan_id, path_id) WHERE path_id IS NOT NULL`。
- `run_audit_path` 完成 finding 时立即 upsert `findings`。
- 最终 runner 落库改为同 key upsert，避免重复。
- 验收：扫描运行中 `/api/scans/{id}/findings` 返回 Agent 路径 finding；最终落库不重复。

## 任务 2：超时/失败状态与进度

- `need_more + reason 含“超时”` → `audit_paths.status=timeout`。
- `reason 含“审计失败”` → `status=error`。
- `coverage` 增加 `done/timeout/error`。
- 扫描详情显示：已审/总数、finding、pending、timeout、tokens。
- 验收：超时路径不再 endless pending；UI 能看到 Agent 进度。

## 任务 3：Harness MVP

- DDL：`verification_runs(id, scan_id, finding_id, path_id, cwe, language, harness_code, status, verdict, exit_code, stdout, stderr, evidence, duration_ms, created_at)`。
- `control/harness.py`：
  - LLM 生成 harness（严格 JSON：language/code/summary）。
  - 沙箱执行：配置化 image、`network=none` 默认、只读、cap_drop、no-new-privileges、timeout。
  - 输出约定：`HARNESS_VERIFIED` / `HARNESS_NOT_TRIGGERED`。
  - 结果写 `verification_runs`；finding verdict 仅 `verified/plausible`，不自动删除。
- API：`POST /api/findings/{id}/verify`、`GET /api/scans/{id}/verifications`。
- UI：Finding 抽屉增加“Harness 验证”和结果。
- 验收：mock 沙箱单测；真实验证在没有镜像时返回明确 `environment_error`，不伪报 verified。

## 任务 4：验证

- pytest / ruff / mypy / frontend build。
- Playwright 扫描详情 + finding 抽屉。
- 重新扫描 JVWA（OSS=true、强 deep model）观察运行中 findings。

## 安全

- Harness 代码必须过危险模式检查；默认无网络；不接受宿主路径挂载；不暴露 Docker socket。
- 不做反弹/交互 shell。
- 远程目标仍只允许读探测。
