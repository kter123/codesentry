# CodeSentry M2（数据与 RAG）实现计划 = Spec v1.0

> **面向 AI 代理的工作者：** 必需子技能：使用 subagent-driven-development（推荐）或 executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法跟踪进度。
>
> - **spec 审计结论（§0 第 3 步）：** 已审计（2026-10-18）。对照 agent.md v1.4 §8/§9 M2 定义（pgvector 入库、AST 切块、Embedding 双通道、kb 导入、混合检索 API）：全覆盖；M3.5 的 vuln_cases/audit_patterns/scan_strategies 不在本轮（agent.md 记载 M2 先行交付 code/kb 双库不影响 M3 启动）；数值照抄；无越界。**审计结论：通过。**
> - **需求源：** 根目录 `agent.md` v1.4

**目标：** 数据与 RAG 底座——pgvector 代码/知识双库、tree-sitter AST 函数/类切块、Embedding 双通道（OpenAI 兼容 + 本地 bge-m3，按配置切换）、`kb import` 命令、混合检索（向量 + 全文）API。

**架构：** 复用 M1 模型层与 M0 配置层；新增 `rag/`（切块 + embedding + 检索）、`db/`（连接池 + DDL + 入库查询）。DDL 全表在本轮落地 `scans/findings/code_chunks/kb_chunks/budget_ledger/node_runs/agent_configs/prompt_versions/skills/skill_versions/skill_assignments/checkpoint 交 LangGraph M3`（§8 全量目标清单 M0/M1 预留；M2 落本里程碑需要的最小集 + 骨架表）。**检索 API 提供同步 Python 函数层**（M3 agent 直接调用），M2 不做 HTTP API（WebUI M5）。

**技术栈：** psycopg3 连接池 / pgvector 索引 / tree-sitter（py-tree-sitter + 各语言 grammar 包）/ openai 客户端（兼容接口）；uv 依赖逐项记录 license。

---

## 全局约束（自 agent.md 逐条）

- RAG 五库角色（FR-5）——M2 先行两库：**code_chunks**（AST 函数/类切块 + 签名/调用关系）、**kb_chunks**（CWE/OWASP + 用户规范）；vuln_cases/audit_patterns/scan_strategies M3.5
- 切块粒度：AST 函数/类粒度（tree-sitter，借鉴 RepoAgent）（D9）；向量 = 代码摘要 + 签名 + 调用关系
- Embedding 双通道（D10）：① OpenAI 兼容远程（CODESENTRY_EMBEDDING_MODEL）；② 本地 bge-m3 挂载盘 vLLM/Ollama 暴露 OpenAI 兼容协议。二者按配置切换；维度入库时自动探测
- 数据本地化（NFR-3）：代码、向量、结果全存本地 PostgreSQL（挂载盘）；代码不外发，仅 LLM 请求按需携带必要片段
- kb 导入 CLI：`codesentry kb import <dir>`（D13）
- 连库集成测试用 testcontainers 或本机 compose 库（§10）
- Schema 边界：业务表进 `codesentry` schema；checkpoint 表 M3 起进 `langgraph` schema
- 随包不带第三方规则/语料限制对 kb 同样适用（§3——kb 内容由用户提供）

## 审查重点（Review Focus）

1. **Embedding 维度不一致写入同表**——在建表/入库时按实测维度生成向量列约束（入库时 auto-detect + 显式记录每 chunk 的 model/dims；检索时校验模型一致）
2. **全文检索中文转义/分词失败**——kb 中文文本入库建 GIN 索引用 `to_tsvector('simple', ...)`（不踩分词器配置）；测试含中文样例
3. **pgvector 检索返回 Scores 混乱**——统一 cosine distance（`<=>`）；API 输出 `score = 1 - distance` 全部归一
4. **连接池未关闭泄漏**——pool context-manager 化；测试关闭后无残留连接
5. **kb import 重复导入**——按 content sha256 幂等：同 hash 跳过；不同则新版本记录

---

## 文件结构

```
src/codesentry/
├── db/
│   ├── pool.py              # psycopg 连接池（context manager）
│   ├── ddl.py               # 全量表 DDL（M2 最小集 + 骨架）——扩展 schema.render_ddl
│   └── repo.py              # 入库/检索 DAO（chunk upsert、检索、findings 基本写）
├── rag/
│   ├── __init__.py
│   ├── chunker.py           # tree-sitter AST 函数/类切块
│   ├── embedding.py         # 双通道 EmbeddingClient（远程 openai 兼容 / 本地 bge-m3 同协议）
│   └── retrieve.py          # 混合检索（向量 <=> + tsvector 全文）→ score 归一
├── cli_commands.py          # kb_cmd 接真（import 子命令）
examples/…
tests/
├── test_db_pool.py
├── test_ddl.py
├── test_chunker.py
├── test_embedding.py        # 双通道 mock + 真连探测可 skip
├── test_retrieve.py         # 本机 compose 库实跑（skip-if-no-db）
├── test_kb_cli.py
└── fixtures/code_sample.py
```

---

### 任务 1：连接池 + DDL全量表落地（TDD）

**文件：** 创建 `db/pool.py`、`db/ddl.py`；测试 `tests/test_db_pool.py`、`tests/test_ddl.py`

**M2 落地表（最小集 + 骨架，全部 codesentry schema）：**
- `scans`：id/bigserial、created_at、repo_path、license_oss bool、license_declared_at、mode full/diff、prompt_snapshot jsonb、skill_snapshot jsonb
- `findings`：id、scan_id FK、rule_id、cwe、severity、confidence、file、line、end_line、message、engine、taint_metadata jsonb、exploit_chain jsonb、poc_path、verdict、execution_log sql（M3 填充逻辑）
- `code_chunks`：id、project、path、symbol_name、symbol_kind（function/class）、start_line、end_line、signature、docstring、call_refs jsonb、content、embedding vector（无固定维度——M2 建表用 `vector` 不限维，改为 text 保存 dims？pgvector 要求 dimension on CREATE；此处列类型用 `vector(3072)` 不合适。方案：**建表时 dims 未定，用 `vector` 类型不带维度**（pg16 支持 untyped vector）→ 入库时维度一致即写入；跨维报错就是防护）、lang、content_sha256 unique-ish
- `kb_chunks`：id、source、title、content、content_sha256、embedding vector、lang
- `budget_ledger`、`node_runs`、`agent_configs`、`prompt_versions`、`skills`、`skill_versions`、`skill_assignments`（骨架字段，M3 填充逻辑）
- `scans.prompt_snapshot`/`skill_snapshot`（snapshot jsonb 复现活跃字段）

- [ ] 步骤 1 测试（ddl 断言含全部表名 + pgvector 扩展；pool 连本机 codesentry-db 若在则 connect，否则 skip）
- [ ] 步骤 2 失败确认
- [ ] 步骤 3 实现 pool.py（`@contextmanager get_conn()` 基于 psycopg_pool；init 时 `options='-c search_path=codesentry,public'`）
- [ ] 步骤 4 测试通过
- [ ] 步骤 5 `feat(m2): db pool + full-table DDL skeleton (§8)`

### 任务 2：tree-sitter AST 切块（TDD）

**文件：** 创建 `rag/chunker.py`；测试 `tests/test_chunker.py` + `tests/fixtures/code_sample.py`

- [ ] 步骤 1 测试：python fixture 切出函数级（name/lines/signature/docstring）；类切出方法归属；跨文件分 jaki 语言（六门各有 chunker 分支—tree-sitter 语法树 node_type 差异)
- [ ] 步骤 3 实现：`chunk_code(path, lang) -> list[Chunk]`；`Chunk(symbol_name/symbol_kind/start/end/signature/docstring/call_refs/content)`；python 精确实现作基准，其余五语言用 tree-sitter 通用 function_definition 节点判断
- [ ] 步骤 5 `feat(m2): tree-sitter AST function/class chunker (D9)`

### 任务 3：Embedding 双通道（TDD）

**文件：** 创建 `rag/embedding.py`；测试 `tests/test_embedding.py`

- [ ] 步骤 1 测试：远程 openai 兼容 client（HTTP mock）/本地 bge-m3（同兼容协议也走 openai client，仅 base_url 不同）；维度探测缓存；**model 未配置时抛 RuntimeError（不能默认走远程泄漏代码）**
- [ ] 步骤 3 实现：`EmbeddingClient(config)` 按 `model_base_url` 是否命中本地（/Volumes/… 或 localhost）也好，均走 OpenAI 兼容 `/v1/embeddings`；`embed(texts) -> list[list[float]]`；`model_name`/`dims` 属性
- [ ] 步骤 5 `feat(m2): embedding dual-channel client (D10)`

### 任务 4：入库 + 混合检索（TDD，连本机库）

**文件：** 创建 `rag/retrieve.py`、`db/repo.py`；测试 `tests/test_retrieve.py`

- [ ] 步骤 1 测试（skip-if-no-db）：kb import 幂等（同 hash 二次导入 skip）；code_chunks 入库后混合检索命中期望 senbøl；中文 kb query 命中
- [ ] 步骤 3 实现：`upsert_code_chunks / upsert_kb_chunks`（ON CONFLICT content_sha256）；`hybrid_search(pool, collection, query_text, query_vec, top_k)`：`0.6*vec + 0.4*tsvector` 加权（权重常量），score 归一 0–1
- [ ] 步骤 5 `feat(m2): pgvector hybrid retrieval + upserts (FR-5)`

### 任务 5：`kb import` 命令接真（TDD）

- [ ] 测试 + 实现 + `feat(m2): kb import command wired (FR-5 kb_chunks)`

### 任务 6：收尾（验收 + 报告）

- [ ] ruff/mypy/pytest 全量；本机库集成测试实跑；依赖 license 逐项记录进 `doc/m2-deps-license.md`
- [ ] `feat(m2): acceptance — tests + deps license record`（认证恢复后 push）

---

## 任务依赖

任务 1 → {2,3} 并行 → 4（依赖 2+3）→ 5（依赖 4）→ 6。真机联调集中在任务 4/6（compose 库已运行）。
