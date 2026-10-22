# RAG 经验层规格审计

## 覆盖

| 目标 | 覆盖 | 结论 |
|---|---|---|
| Triage 使用历史案例 | `run_retrieval` + `triage_one` user 上下文 | ✅ |
| PoC 使用历史案例/PoC 模板 | evidence 传入 `gen_poc` | ✅（依赖 LLM 使用） |
| Recon 使用项目策略 | `build_profile.strategies` | ✅ |
| GraphRAG 调用图 | code_graph build + BFS + graph_context | ✅（Python） |
| 人工复核沉淀 | `promote_findings` on scan/resume | ✅ |
| 经验库检索 API | `/api/experience/*` | ✅ |

## 发现

1. **嵌入检索未接**：当前用 PostgreSQL FTS，`embedding` 字段预留；语义相似度在陌生表述下弱。后续接入 bge-m3。
2. **仅 Python 图**：chunker 只支持 Python；其他语言 code_graph 为空，需在 M3.5 后续扩展。
3. **案例质量**：`keep` 也可能包含误报；自动沉淀可能与人工意图冲突。建议默认只沉淀 `verified/confirmed`，`keep` 需人工触发 promote。
4. **策略匹配粗糙**：用 languages/frameworks 文本匹配，未按仓库规模/框架版本细分。
5. **GraphRAG 证据只在 retrieval 中附带**，Triage 是否真正使用取决于 LLM；需要在 Prompt 中明确“graph 邻居可用于可达性”。
6. **测试**：覆盖 add/search/promote/build/neighbors；未覆盖向量检索（未实现）。

## 判定

规格可执行，已实现最小闭环；1/2/3 作为已知限制。建议：自动沉淀改为仅 verified，keep 通过显式 promote API。
