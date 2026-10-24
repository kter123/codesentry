# 平台扩展：AI 辅助 / 知识库 / 审查协作 / 生命周期 / SDK

> 日期：2026-10-22。覆盖 FR-35（知识库运营）、FR-36（AI 辅助）、FR-39（数据生命周期）、FR-41（SDK）、FR-44（审查协作）最小闭环。

## 1. Ask CodeSentry（FR-36）

- `POST /api/assist/ask` body `{question, scan_id?}`。
- 上下文：扫描最近 artifacts（≤30）+ findings（≤20）≤12k 字符；Prompt 声明仓库内容不可信、证据不足说不知道。
- 使用 Agent 绑定/默认 LLM Profile；返回 `{answer, sources, scan_id}`；无 LLM 503、空问题 400。
- UI：ScanDetail 头部“问 AI”抽屉，展示回答与来源。
- 限制：非流式、无跨扫描/知识库检索、单租户。

## 2. 知识库运营（FR-35）

- `GET /api/kb/stats`：chunk/source 统计。
- `POST /api/kb/search`：全文检索 kb_chunks（向量检索预留）。
- `POST /api/kb/import`：按段落切块导入（幂等 content_sha256，无 embedding）。
- 限制：无目录/zip 导入 UI、无重建索引/切块预览；后续接 M2 embedding。

## 3. 审查协作（FR-44）

- 表 `review_comments(scan_id, finding_id, author, body, created_at)`。
- `GET/POST /api/scans/{id}/comments`；支持 `finding_id` 过滤。
- 限制：无 @提醒/指派/SLA/批量决策/评论 UI。

## 4. 数据生命周期（FR-39）

- `POST /api/ops/retention` `{days}`：清理超期 scans、子表、容器/网络、deploy 工作区。
- `GET /api/ops/disk`：work 目录占用。
- 限制：无定时任务/导出/脱敏；保留策略仅按天数。

## 5. SDK（FR-41）

- `codesentry.sdk.CodeSentryClient`：health/create_scan/list_scans/get_scan/findings/artifacts/verify_artifacts/resume/ask/usage。
- 支持 Bearer Token、自定义 transport（测试）。
- 限制：未生成 TypeScript 客户端；错误类型未细分。

## 6. 测试与验证

- `test_control_api`：AI assist、KB stats/import/search、comments、retention/disk。
- `test_sdk`：MockTransport 校验 URL/Token/响应。
- 全量回归/ruff/mypy 见提交记录。

## 7. 审计结论

最小闭环可用，均与“多 Agent 分析可解释、可复用、可清理”目标一致。剩余：多租户/配额、通知渠道（邮件/Slack/飞书已排除）、编排 UI、A/B 对比图、Copilot、评论 UI、向量检索/重建。

## 8. 后续补充（2026-10-22）

- 编排 UI 已接服务端：保存/激活/载入 `/api/graph-templates`（此前已实现）。
- 审查评论 UI：ScanDetail finding 抽屉可查看/添加评论（POST `/api/scans/{id}/comments`）。
- 密钥清理：`scripts/scan_secrets.py` 扫描仓库密钥；`scripts/rotate_master_key.py` 轮换 LLM/Embedding 加密主密钥。
- 仍未完成：A/B 对比图（已有评测表/指标展示）、Copilot、向量重排、六语言 GraphRAG、KB 重建/切块预览 UI。
