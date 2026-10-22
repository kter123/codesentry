# Ask CodeSentry 审计/计划/复核

## 计划
1. `control/assist.py`：上下文 + LLM + sources（已完成）。
2. `POST /api/assist/ask` 线程池（已完成）。
3. ScanDetail “问 AI”抽屉（已完成）。
4. 测试/全量/build（进行中）。

## 审计
- 风险：上下文截断丢失证据；模型可能编造；未流式；单租户。
- 缓解：Prompt 强制“证据不足说不知道”；返回 sources 便于核对；上下文按 artifact/finding 标注。
- 测试：`test_assist_ask` mock LLM；错误码覆盖空问题/无 LLM。

## 复核
- R1：LLM 同步阻塞 → 线程池。
- R2：回答无来源 → 返回 sources；UI 展示。
- 已知：非流式、无知识库/跨扫描、无租户。
