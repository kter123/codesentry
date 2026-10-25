# CodeSentry 剩余需求实现规格（P0 + P1）

- 日期：2026-10-25
- 基线：`4320dc3 feat(codeql): webui settings, engine status and SARIF fixes`
- 依据：`doc/2026-10-25-remaining-backlog.md`、`doc/2026-10-24-requirements-core.md`
- 范围：P0 全部 8 项 + P1 全部 11 项。P2 明确不做：多租户/部门隔离、远程 PoC target、交互式/反弹 shell、CodeQL packs 自动下载、自动修复补丁、IDE 插件、DAST/容器/IaC 扫描。

## 0. 不可破坏的架构约束

1. **图是一等公民**：代码 → 图（节点/边）→ 路径 → Agent；引擎输出只能作为图增量/hint，不能直接成为最终 finding。
2. **审计与部署 Agent 主导**：不得在流水线里写死“某 CWE 必报/某项目必部署”；Agent 通过工具取证、决定结论与部署方式。
3. **Prompt/LLM/工具/Skills 可配置**：所有 Agent 的 Prompt、模型、工具白名单、技能白名单可从控制面修改；代码内仅保留不可删除的安全/输出契约尾。
4. **RAG 是 Agent 的经验工具**：不是固定 retrieval 阶段；路径审计、Triage、PoC 都可按需调用。
5. **安全边界**：不硬编码密钥；密钥只存 `.env` 或加密库并掩码回显；PoC 仅本地/授权容器；Docker 端口只绑 `127.0.0.1`；默认 `POC_RUN=off`；默认不访问远程 registry。
6. **多租户不做**；单租户 RBAC 保持。

## 1. P0-1 CodeQL 全链路

### 1.1 需求
- 一次扫描可从上传/Git/diff 进入，经 GraphBuild → Scan（Semgrep/CodeQL/Joern）→ 图增量 → 路径构建 → 路径审计 → Triage → Deploy → PoC → Report。
- CodeQL 必须支持按仓库识别语言选择对应 database/query pack，而不是只取 `languages[0]`。
- CodeQL SARIF 的 `artifactLocation.uri` 必须归一化为仓库相对路径，保证 hint 能锚定到图函数；`file://`、绝对路径、URL 编码都要处理。
- CodeQL codeFlows 生成的 `dataflow` 边必须能在 `/graph`、`/paths` 和报告中看到，并带 `provenance=codeql`。
- CodeQL 不可用/单语言失败必须降级为其他引擎+纯图审计，不阻断扫描。

### 1.2 验收
- 合成 Java servlet（`getParameter → Runtime.exec`）完整扫描后：
  - `engine_results_meta` 中 `codeql.status=ok`；
  - `findings` 至少 1 条 command injection；
  - `graph_delta.engine_graph.codeql.ok=true` 且 `dataflow>0`；
  - `/api/scans/{id}/graph` 至少 1 条 `provenance=codeql` 的 `dataflow` 边；
  - `/api/scans/{id}/paths` 至少 1 条 `feasibility=proven`。
- Python/JavaScript 各有一个 synthetic source→sink 样例，CodeQL 扫描能产出语言对应的 SARIF，不要求一定有 finding。
- `CodeQL status` 返回 languages/packs 与当前 search-path 一致。

## 2. P0-2 路径级 PoC

### 2.1 需求
- PoC 必须以 **path_id** 为主键上下文，而不仅是 finding；同一 finding 若来自不同入口路径，PoC 必须体现入口差异。
- PoC 输入包含：入口节点（method/route/permission/file:line）、source/sink 节点、路径节点/边、目标 `target_url`（若已部署）。
- HTTP 类 PoC 优先使用实际入口 URL：`target_url + route`；仍必须保留 `{CANARY_URL}` 回调占位符用于证明。
- 本地类 PoC 必须保留 `{CANARY_CMD}` / `{CANARY_FILE}` 之一。
- PoC 结果新增 `path_id`、`entry_url`、`verification_method`、`verification_nonce`，前端可见。
- 无 path_id 的旧 finding 继续走原逻辑（向后兼容），不得报错。

### 2.2 验收
- 单测：构造带 `path_id` 的 finding + `audit_paths` 行，PoC prompt 的 user JSON 包含 `path_context.entry.method/route/full_url`，输出结果含 `path_id`。
- 合成 Flask `eval` 项目：路径级 PoC 能生成脚本；sandbox 模式下 canary 结果与路径绑定。
- 前端 Finding 抽屉显示 PoC 路径 ID 与入口 URL。

## 3. P0-3 路径 UI 与图联动

### 3.1 需求
- 扫描详情“审计路径”表：点击行打开路径抽屉；显示路径节点、边、证据、finding 关联。
- 每条路径提供“在图中高亮”按钮，跳转 `/scans/:id/graph?path_id=<id>`。
- GraphView 读取 `path_id`，拉取路径详情，自动高亮路径节点/边（宽度/描边/颜色），并聚焦入口节点。
- 图节点加载上限不足时，必须保证路径节点被包含（后端支持 `focus` 参数或在返回中附加路径节点）。
- 提供“清除高亮”操作。

### 3.2 验收
- GraphView 的路径节点带 `borderColor`/`borderWidth`，路径边更粗；非路径节点降低透明度。
- 路径 ID 不存在/已删除时显示非阻断提示，图正常展示。
- 前端构建通过。

## 4. P0-4 DeployAgent 成功部署 kvf

### 4.1 需求
- 优先使用本机已有 Java 镜像（`maven:3.8-openjdk-8` 等），只有显式 `allow_remote` 才使用远程 registry。
- Maven 配方支持 jar 与 war；jar 直接 `java -jar`，war 用可用的本地 Tomcat/应用服务器镜像或明确 degraded。
- 数据库/缓存依赖（MySQL/Redis）缺失时，DeployAgent 必须：
  - 仍完成构建/启动尝试；
  - 返回 `degraded` 而不是 `disabled`（构建成功但健康检查失败）；
  - `deploy_log` 记录缺失依赖、目标 URL、容器日志尾部。
- `deploy_image_pull=never|missing|always` 真正生效；`never` 时不得触发任何 pull。
- 部署成功后 `target_url` 只绑定 `127.0.0.1`。

### 4.2 验收
- 真实 kvf 源码：使用本地 `maven:3.8-openjdk-8` 构建成功；若因 MySQL 启动失败，状态为 `degraded`，日志包含 MySQL/连接失败原因。
- 单测：`choose_java_image` 优先本地；`_pull_policy` 下 `never` 不调用 pull；war 命令包含 war 分支。
- 无本地 Java 镜像且 `allow_remote=false` 时返回 `disabled` 且原因明确。

## 5. P0-5 路径审计成本收敛

### 5.1 需求
- 新增配置：
  - `audit_max_paths`：单扫描最多认领路径数，默认 240；
  - `audit_entry_only_max`：entry-only 路径最多认领数，默认 48；
  - `audit_path_timeout_s`：单路径 Agent 超时，默认 60；
  - `audit_priority`：排序策略（`proven_first` 默认）。
- `claim_paths` 必须按 `feasibility proven > likely > weak`、`score DESC`、`kind != entry_only` 优先；entry-only 超限后不再认领。
- 达到 `audit_max_paths` 后剩余 pending 路径保留，由 `audit_finalize` 作为低置信候选/覆盖说明，不静默丢失。
- `coverage` 返回 `total/pending/auditing/finding/clean/blocked/error/entry_only/dataflow_paths/batch/max_rounds/entries_covered/sinks_covered/sinks_total`。
- 前端路径页展示这些指标。

### 5.2 验收
- 单测：构造 20 条 proven + 20 条 entry_only + 小上限，认领顺序 proven 优先，entry_only 不超过上限，总认领不超过 max。
- 路径超时使用配置值，不再硬编码 60。
- 扫描在默认预算下能收敛到 triage，不无限循环。

## 6. P0-6 多语言引擎图

### 6.1 需求
- ScanAgent 使用 `profile.languages` 为 CodeQL 生成多语言任务；Semgrep 单次覆盖仓库；Joern 仅 Java。
- CodeQL 每个语言独立 database/SARIF，输出文件名含语言，图增量合并。
- 至少 Python 与 JavaScript 的 CodeQL codeFlows 能转 `dataflow` 边；无 flow 时仍产出 calls/imports 或明确统计 0。
- 语言不支持/缺 pack 时单语言失败不影响其他语言。

### 6.2 验收
- Python synthetic `request.args.get → eval` 扫描：`engine_graph.codeql` 有记录；若 CodeQL 无 flow，则 tree-sitter 图仍有 source/sink/taints_to，路径可达。
- JavaScript synthetic `req.query → child_process.exec` 扫描：同上。
- 单测：多语言 specs 生成 2 个 CodeQL 命令，SARIF 解析后 dataflow 边写入。

## 7. P0-7 浏览器级验证

### 7.1 需求
- 提供可重复的 UI smoke 脚本，覆盖 16+ 路由、登录/本地模式、概览、扫描详情、路径抽屉、GraphView、Settings CodeQL/通知、Agent/Prompt/KB 页面。
- 无 Playwright Chromium 时使用本机 Safari WebDriver（`safaridriver`）或明确记录不可用原因；不得用 HTTP 200 冒充渲染验证。
- 脚本检查：页面无白屏（`#app` 有子节点）、无未捕获 JS 错误、关键文本存在。

### 7.2 验收
- 脚本可在本机运行并输出每路由 PASS/FAIL；失败必须给出原因。
- 若环境确实无法启动浏览器，记录 `BLOCKED` 与具体错误，不虚报通过。

## 8. P0-8 审计稳定性回归

### 8.1 需求
- 提供路径级回归数据集（至少 3 条：命令注入、SSRF、安全对照），每条含 repo 文件、hint、期望 verdict/关键 CWE。
- `scripts/eval_path_audit.py` 支持 `--dataset`，输出每条路径多轮 verdict、consistency、finding 命中率。
- 新增离线回归测试：用 deterministic fake LLM 跑 3 条路径，断言 finding/clean 分类稳定；真实 LLM 评测作为 live 脚本，不纳入 CI。
- 文档记录真实 LLM 的方差与建议温度/模型。

### 8.2 验收
- `pytest tests/test_path_eval_regression.py` 稳定通过。
- `scripts/eval_path_audit.py --dataset tests/fixtures/path_eval.json --runs 3` 可运行。

## 9. P1-9/10 路径统计与详情

- `/api/scans/{id}/coverage` 扩展统计；`/api/scans/{id}/paths/{pid}` 返回 `nodes_detail/edges_detail`（解析 graph_nodes）。
- 扫描详情路径 tab：统计 tags、行点击抽屉、节点表、边表、证据 JSON、源码切片入口、图高亮按钮。
- 验收：路径详情抽屉可打开；节点/边数与 DB 一致；无路径时空态不报错。

## 10. P1-11 通知渠道

- 支持 `generic`（现有 HMAC）、`feishu`、`dingtalk`、`wecom`、`email`。
- webhook 表扩展 `name/kind/headers/last_status/last_error`；创建/列表/删除/测试 API。
- 飞书/钉钉/企业微信按各自消息体发送；secret 用于签名（飞书 timestamp+sign，钉钉 sign 参数）。
- 邮件使用 SMTP 设置（host/port/user/password/from/to/tls），密码加密存储、掩码回显。
- 事件 `scan.completed/scan.failed/review.completed` 均投递；失败重试但不超过 2 次。
- UI 设置页新增“通知渠道”面板：列表、新增、测试、删除；SMTP 配置与测试。
- 验收：单测 mock httpx/smtplib 断言四种消息体与签名；API CRUD；无 secret 泄露。

## 11. P1-12 项目与定时扫描

- 新表 `projects(id,name,repo_path,git_url,oss,enabled,created_at,updated_at)`、`scan_schedules(id,project_id,name,cron,enabled,last_run_at,next_run_at,created_at)`。
- API：`/api/projects` CRUD、`/api/schedules` CRUD、`/api/schedules/{id}/run`。
- 支持 5 字段 cron（`*`, 数字, `a-b`, `*/n`, 列表）。启动时后台调度线程每 30s 检查 due schedule；只允许 work 根目录内 repo_path 或 HTTPS git_url。
- 定时扫描创建 scan 并复用现有 `_run_scan_bg`，失败写 `error_reason`。
- UI 新页面“项目与定时”：项目表、Schedule 表、创建/启停/立即运行。
- 验收：cron next-run 单测；API CRUD；调度器不重复触发同一分钟；无 repo 路径穿越。

## 12. P1-13 自定义 Agent

- 新表 `agent_presets(id,name,base_agent,description,system_prompt,tools_allow,skills_allow,capabilities,enabled,version,created_at,updated_at)`。
- `agent_configs` 新增 `preset_id`；运行时若绑定 preset：
  - 用 preset.system_prompt 经过 `compose_prompt(base_agent, ...)` 保留安全/输出契约尾；
  - 合并 preset 的 tools/skills/capabilities；
  - 快照记录 `preset_id/version`。
- API：`/api/agent-presets` CRUD、`/api/agents/{name}/bind-preset`；AgentDetail 提供 preset 选择/编辑。
- 验收：绑定 preset 后 dry-run 的 system_prompt 包含 preset 内容与 invariant tail；解绑恢复原 Prompt；不支持的 base_agent 返回 400。

## 13. P1-14 Agent 试跑对比

- `/api/agents/{name}/compare` 输入 `state`、`prompt_a`、`prompt_b`（版本号或 preset id），使用同一输入运行两次（可 `dry_run=true` 只比较渲染后的 prompt/token/工具集合）。
- 返回 `a/b` 的 system_prompt、token_est、skills、capabilities、warnings、diff。
- AgentDetail 增加“试跑对比”对话框，默认 dry-run，可显式勾选“调用 LLM”；LLM 失败不阻塞。
- 验收：dry-run 对比无需 LLM；两个版本差异可见；非法版本返回 400。

## 14. P1-15 配置导入导出

- `GET /api/config/export` 导出 JSON：prompts（版本/激活）、agent_configs、agent_presets、skills（元数据）、graph_templates、webhooks（去掉 secret）、settings（只导出非密钥键，密钥键显示 `""`）。
- `POST /api/config/import` 支持 `mode=merge|replace`，逐项校验；不导入密钥明文、不导入 `api_key_cipher`。
- API 需 admin；导出带 `version/schema_version/exported_at`。
- UI 设置页新增导出下载、导入文件选择、结果摘要。
- 验收：导出不含任何 key/cipher/secret；导入后 prompt/agent 生效；非法 JSON 返回 400；replace 不删除 LLM profiles。

## 15. P1-16 报告路径可视化

- `report.md` 新增“攻击路径”章节：每条 path 的 entry→source→sink、节点表、边类型、可行性、分数、finding 链接；附 Mermaid `flowchart LR`（节点过多截断 20 个）。
- SARIF 的 finding properties 增加 `path_id`（已有 taint_metadata 不破坏）。
- 验收：报告包含路径章节与 Mermaid；没有路径时输出“无路径数据”；测试断言关键字段。

## 16. P1-17 大图 package 折叠

- GraphView 增加“按包聚合”开关：按文件目录聚合为 `package:<dir>` 节点，边聚合计数；保留“展开包”能力（点击包节点将 kindFilter 设为该包下节点或取消聚合）。
- 聚合后节点上限仍 800，显示包节点数/原始节点数/边数。
- 验收：>2000 节点图开启聚合后渲染节点数显著下降；关闭恢复；无 JS 错误。

## 17. P1-18 生命周期清理

- `retention.purge_scans` 补齐 `audit_paths/audit_rounds/review_comments/agent_artifacts` 等子表。
- 新增 `cleanup_codeql_cache(days)`、`cleanup_orphan_workdirs(days)`、`cleanup_target_images()`。
- `POST /api/ops/maintenance` 接受 `days/codeql_days/orphan_days/clean_images`，返回清理统计。
- Settings/ops 面板提供“立即维护”按钮与磁盘使用。
- 验收：单测/集成测试清理审计表；不删除现有扫描未到期的容器/镜像；CodeQL cache 只删过期目录。

## 18. P1-19 Python SDK / API 补全

- SDK 新增 `list_paths(scan_id,status,limit)`、`get_path(scan_id,path_id)`、`coverage(scan_id)`、`codeql_status()`、`engine_test()`、`export_config()`。
- 全部走现有 REST，不新增重复端点。
- 验收：MockTransport 单测覆盖路径/覆盖度/CodeQL；SDK README/示例更新。

## 19. 交付顺序

1. 基础设施：DDL/配置/路径统计/成本控制。
2. CodeQL 多语言 + 全链路。
3. 路径 PoC + 路径 UI/图联动。
4. Deploy 本地镜像 + kvf 验证。
5. 通知渠道 + 项目/定时 + 自定义 Agent + 对比 + 配置导入导出。
6. 报告路径图 + 图聚合 + 生命周期 + SDK。
7. 浏览器 smoke + 回归数据集 + 全量测试/文档/推送。

## 19.1 审计后修订（2026-10-25）

以下为 spec 审计后强制生效的修订：

1. **通知 secret 加密**：新 secret 用 `encrypt_secret` 加密存 `webhooks.secret`（`enc:` 前缀），旧明文兼容读取；列表/导出永不返回 secret。
2. **CodeQL URI 归一**：`_parse_sarif(path, repo)` 使用 `normalize_sarif_uri`，覆盖 `file://`、URL 编码、绝对/相对路径。
3. **调度原子性**：scheduler 以 `UPDATE ... WHERE next_run_at<=now() AND enabled RETURNING` 抢占并推进 next_run_at，避免多 worker 重复扫描。
4. **镜像拉取策略**：DockerDeployer 统一 `_ensure_image(image, policy)`；`never` 只查本地，缺失 disabled。
5. **语言去重**：`typescript→javascript` 归一后去重，SARIF 每语言唯一。
6. **PoC entry_url**：仅部署 ready 且 target_url 存在时拼 URL；否则只给 route 与 `{CANARY_URL}`，不臆造 host。
7. **路径上限统计全量**：`audit_max_paths`/`entry_only_max` 统计 `status != 'pending'` 的已审计路径，跨轮次生效。
8. **preset invariant tail**：preset 正文渲染后强制追加代码内安全/输出契约尾。
9. **配置导出排除敏感键**：`*_api_key`、`*_secret`、`codeql_build_command` 一律不导出、不导入。
10. **邮件渠道占位**：`kind=email` 时 `url='smtp'`，收件人放 headers.to；API 校验 kind。
11. **图 focus**：Graph API 支持 `focus` 并把 focus 节点置顶；前端传 path 节点并优先保留。
12. **项目路径限制**：project.repo_path 必须在 work 根内；git_url 复用 HTTPS/私网校验。
13. **报告路径只查本扫描**：无 scan_id 不查 audit_paths。
14. **compare 默认 dry-run**：真实 LLM 需 `use_llm=true` 并走受控 LLMClient。
15. **镜像清理**：仅 `codesentry-target-*` 且无容器引用；默认不清理。
16. **浏览器 smoke**：失败输出 `BLOCKED` 与原因，不伪造 PASS。

## 20. 质量门禁

- `pytest` 全绿（含新增测试），ruff/mypy 绿。
- 前端 `npm run build` 通过。
- 真实 CodeQL 至少 Java + Python/JS 各一次。
- kvf 真实部署尝试记录。
- UI smoke 有 PASS/BLOCKED 证据。
- 不提交密钥、`CodeScan-Artex/`、`kvf-admin-master.zip`。
