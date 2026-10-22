# Prompt A/B 与自动评测审计

- 分流：`ab_json`/`pick_version`/快照 `ab_arm` 已实现；`_insert_scan` 先取 scan_id 再建快照，保证稳定分流。
- 评测：内置 3 例，真实 Triage；API 线程池；结果写 `prompt_evals`；UI 展示指标。
- 风险：数据集小；真实 LLM 配额/延迟；无 LLM 时 503；A/B 对比图未做。
- 测试：`test_prompt_eval_run`（mock LLM/triage）+ control API 契约；全量回归见最终记录。
- 判定：通过；数据集扩充/A-B 对比图列为后续。
