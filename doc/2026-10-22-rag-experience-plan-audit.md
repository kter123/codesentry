# RAG 经验层计划审计

1. **覆盖**：DDL、经验库、GraphRAG、Retrieval/Triage/Recon 接入、反馈闭环、API、测试均有对应任务。
2. **风险**：仅 Python 图、FTS 无向量、自动沉淀质量；已列为已知限制。
3. **测试**：`test_rag_experience` 覆盖 add/search/promote/build/neighbors；缺少真实扫描 evidence 断言（LLM 场景）。
4. **验收调整**：全量测试需在测试环境关闭 deploy（已由 conftest 统一），避免测试触发真实容器。
5. **判定**：通过；进入实现（已完成）与复核。
