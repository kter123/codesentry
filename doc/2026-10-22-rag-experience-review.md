# RAG 经验层双轮 Code Review

## 第一轮：正确性 / 数据

| ID | 发现 | 处置 |
|---|---|---|
| R1-1 | `LIKE 'unit:%'` 在 psycopg 参数化中被当成占位符 | **已修**：全部改为 `LIKE %s` 参数 |
| R1-2 | `scan_strategies.strategy DEFAULT '{}'` 在 f-string DDL 中语法错误 | **已修**：`{{}}` |
| R1-3 | `promote_findings` 可能重复沉淀 | **已修**：按 `source=scan:{id}:{rule}:{file}:{line}` 去重 |
| R1-4 | 经验库为空时无兜底 | **已修**：`seed_experience()` 幂等写入 4 条内置模式 |
| R1-5 | code_graph 仅建节点无边 | **已修**：call_refs → 本地符号建 calls 边；测试覆盖 |

## 第二轮：集成 / 回归 / 限制

| ID | 发现 | 处置 |
|---|---|---|
| R2-1 | Triage 是否真的使用经验 | **已修**：user JSON 加入 `vuln_cases/patterns/graph` |
| R2-2 | PoC 是否拿到案例 | evidence 传入 `gen_poc`；Prompt 已要求参考证据 |
| R2-3 | Recon 是否使用策略 | `build_profile` 增加 `strategies` |
| R2-4 | 自动沉淀误报风险 | 扫描只沉淀 `verified/confirmed`；人工复核后沉淀 `keep`；可 `POST /promote` |
| R2-5 | 仅 Python 图 / 无向量 | 记录为已知限制，不在本批扩展 |
| R2-6 | 测试污染 | 使用唯一 project + 清理 findings/scans/vuln_cases/code_graph |

## 验证

- `uv run pytest -q tests/test_rag_experience.py`：3 passed。
- 全量回归：**271 passed, 2 skipped, 1 xfailed**。
- `ruff` / `mypy`：通过。

## 结论

RAG 最小闭环可用：经验检索进入 Triage/PoC 上下文，策略进入 Recon，GraphRAG 提供 BFS 邻居，复核/验证结果可沉淀为案例。后续优先补：向量检索、六语言图、案例审核与质量评分、知识库运营 UI。
