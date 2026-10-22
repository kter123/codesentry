# Prompt A/B 与自动评测规格

## 1. A/B 分流

- `agent_configs.ab_json`：`{"enabled": true, "a": 1, "b": 2, "ratio": 0.5}`。
- `pick_version(agent, scan_id)`：按 `(scan_id*31 + sum(ord(agent))) % 100 / 100` 稳定分桶；`bucket < ratio` 取 B，否则 A。
- 扫描快照 `prompt_versions[agent]` 记录 `version`、`sha256`、`ab_arm`。
- 未启用 A/B 时取 active 版本。

## 2. 自动评测

- 内置数据集 `EVAL_CASES`（SSRF / SQLi / 安全参数化查询），`selfbuilt`。
- `run_prompt_eval(agent, version, dataset, limit)`：
  - 加载指定版本 Prompt（未指定则用 active）；
  - 对每个 case 调真实 Triage（`triage_one`）；
  - 统计 `tp/fp/tn/fn`、`recall`、`precision`、`fp_rate`、`ece`；
  - 写入 `prompt_evals`。
- API：`POST /api/prompts/eval/run`（线程池执行）、`GET /api/prompt-evals`。
- UI：Prompts 版本栏“运行评测”，展示 Recall/Precision/FP/ECE/样本。

## 3. 验收

1. `pick_version` 对同一 scan_id 稳定、比例符合。
2. 扫描快照含 `ab_arm`。
3. 评测 API 写入 `prompt_evals`，UI 显示指标。
4. 全量测试/ruff/mypy/前端 build 通过。

## 4. 限制

- 内置数据集较小；真实 BMJ 抽样评测需数据集导入（后续）。
- 评测走真实 LLM，受配额影响；无 LLM 返回 503。
- A/B 结果统计按版本聚合，UI 尚未做 A/B 对比图。
