# Prompt A/B 与自动评测复核

- R1：`ab_json` 未在 UI 前，Agent 配置无入口 → 已加智能体 A/B JSON 文本框并保存。
- R1：评测同步阻塞 → 已走 `run_in_threadpool`。
- R2：无 LLM 时异常 → API 503；测试 mock `LLMClient.for_agent`/`triage_one`。
- R2：评测结果只写库不展示 → Prompts 页展示 Recall/Precision/FP/ECE。
- 已知：数据集小；无 A/B 对比图；BMJ 导入后续。
- 验证：control/RAG 测试通过；前端 build 通过；全量回归见最终记录。
