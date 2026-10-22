# RAG 经验层实现计划

**目标：** 建立历史案例/漏洞模式/扫描策略/调用图的最低可用闭环，并接入 Triage/PoC/Recon。

**规格：** `doc/2026-10-22-rag-experience-spec.md`（审计：`...-spec-audit.md`）

## 任务

1. **DDL**：`vuln_cases`、`audit_patterns`、`scan_strategies`、`code_graph_nodes/edges`（已完成）。
2. **经验库服务** `rag/experience.py`：add/search/seed/promote/cases_context（已完成；测试 `test_rag_experience.py`）。
3. **GraphRAG** `rag/graphrag.py`：build/ensure/neighbors/node_for_location/graph_context（已完成）。
4. **Retrieval 接入**：`run_retrieval` 写 vuln_cases/patterns/graph；`run_triage` 用户上下文包含；`build_profile` 写 strategies（已完成）。
5. **反馈闭环**：扫描结束沉淀 verified/confirmed；人工复核后沉淀 keep；`POST /api/scans/{id}/promote`；经验查询 API（已完成）。
6. **测试与验收**：RAG 单测、全量回归、ruff/mypy（待全量）。
7. **文档**：本规格/审计/计划/审计/复核；更新 requirements/agent.md（进行中）。

## 验收

- `uv run pytest -q tests/test_rag_experience.py` 2 passed。
- 全量 tests、ruff、mypy 通过。
- 真实扫描的 evidence 中出现 `vuln_cases/patterns/graph`（可在 artifacts/LLM 上下文中观察）。

## 已知限制

- 仅 Python 调用图；文本检索为主；案例质量/审核未做；GraphRAG 仅 BFS 邻居，未做污点路径规划。
