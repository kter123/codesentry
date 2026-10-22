# Prompt A/B 与自动评测计划

1. `agent_configs.ab_json` + `AgentPatch` + UI 文本框（已完成）。
2. `pick_version` + 快照 `ab_arm` + `_insert_scan(scan_id)`（已完成）。
3. `EVAL_CASES` + `run_prompt_eval` + `prompt_evals`（已完成）。
4. `POST /api/prompts/eval/run` + 线程池（已完成）。
5. Prompts UI “运行评测” + 指标展示（已完成）。
6. 测试/全量/ruff/mypy/前端 build（进行中）。
7. 文档/提交（进行中）。

限制：数据集小、无 A/B 对比图、无 BMJ 导入。
