# 剩余需求 Spec 审计

- 日期：2026-10-25
- 审计对象：`doc/2026-10-25-remaining-backlog-spec.md`
- 结论：**有条件通过**；以下 14 项必须在 plan 中落实，其中 4 项为安全/正确性阻断。

## A. 阻断项（必须修）

| # | 问题 | 影响 | 修订 |
|---|---|---|---|
| A1 | webhook `secret` 当前明文存 DB；spec 只要求掩码回显 | 通知签名密钥泄露 | 沿用 `security/secrets`：新 secret 用 `encrypt_secret` 存储（`enc:` 前缀），读取时解密；兼容旧明文。列表/导出永不返回 secret。 |
| A2 | CodeQL `_parse_sarif` 未接收 repo，`artifactLocation.uri` 可能 `file://`/绝对路径 | hint 无法锚定图，dataflow 边错位 | `_parse_sarif(path, repo=None)` 统一通过 `normalize_sarif_uri`；单测覆盖 `file://`、URL 编码、绝对路径、相对路径。 |
| A3 | 定时扫描多 worker 启动会重复触发；仅 `next_run_at` 无并发保护 | 重复扫描、预算浪费 | scheduler 用 `UPDATE ... WHERE next_run_at<=now() AND enabled RETURNING` 原子抢占并推进 `next_run_at`；按 `schedule_id+minute` 幂等。 |
| A4 | `deploy_image_pull` 当前未真正接入 DockerDeployer | `never` 仍可能拉远程镜像 | 统一 `_ensure_image(image, policy)`：`never` 只查本地，缺失返回 disabled；`missing` 本地缺失才 pull；`always` 先 pull。所有 recipes/Dockerfile 路径都走它。 |

## B. 重要修正（必须修）

| # | 问题 | 影响 | 修订 |
|---|---|---|---|
| B1 | spec 未定义 CodeQL 语言去重：`typescript`/`javascript` 会重复 database | 重复建库、SARIF 覆盖 | `CODEQL_LANG` 归一后 `dict.fromkeys` 去重；`codeql-<dblang>.sarif` 每语言唯一。 |
| B2 | 路径 PoC 的 `target_url` 在 internal 网络下宿主不可达 | PoC 生成错误 URL | `entry_url` 仅在 `deploy_status=ready/target_url` 存在时生成；否则保留 route + `{CANARY_URL}`，不臆造 host。 |
| B3 | 路径认领上限只按“本批”会跨轮次重复超限 | 成本失控 | `audit_max_paths` 统计 `status != pending` 的审计数；`entry_only` 统计 `kind='entry_only' AND status != pending`；在 SQL 中过滤。 |
| B4 | `compose_prompt` 在 preset 正文含“只输出 JSON”时可能跳过 invariant tail | 输出契约被绕过 | preset 渲染后始终追加代码内 invariant tail（显式 `force_tail=True`），与现有逻辑兼容。 |
| B5 | 配置导出若包含 `codeql_build_command` 可能含凭据 | 泄密 | 导出排除 `*_api_key`、`*_secret`、`codeql_build_command`；导入时这些键必须为空/忽略。 |
| B6 | 通知 email 没有 URL，webhooks.url NOT NULL | 无法创建邮件渠道 | 约定 `kind=email` 时 `url` 存 `smtp`（或 `smtp://` 占位），收件人存 headers `to`；API 校验 kind。 |
| B7 | 图 `focus` 只加参数不够，前端仍 slice 800 | 路径节点可能不被渲染 | API 支持 `focus=key1,key2`，把这些节点置顶返回；前端 path_id 时传 focus，并在 slice 前保留 highlight 节点。 |
| B8 | 定时项目允许任意 `repo_path` 会读宿主文件 | 越权读取 | 仅允许 work 根目录内路径；Git URL 复用 HTTPS/私网校验；API 创建时校验。 |
| B9 | 报告路径图直接查 audit_paths 可能跨扫描串数据 | 报告错误 | `run_report` 只用 `scan_id` 查询；无 scan_id 时用 state 内 `path_nodes`，不查库。 |
| B10 | Agent compare 调用 LLM 可能产生未计费调用 | 预算失真 | compare 默认 `dry_run=true`；真实调用必须显式 `use_llm=true`，并走 `prepare_agent` 的 LLMClient（计入 usage）。 |

## C. 可执行性修正

| # | 问题 | 修订 |
|---|---|---|
| C1 | P0-1 “Python/JS 各一个样例”需要明确 fixture | 放 `tests/fixtures/codeql/`：Java `CmdServlet.java`、Python `py_cmd.py`、JS `js_cmd.js`；真实扫描脚本 `scripts/validate_codeql_fullchain.py`。 |
| C2 | P0-8 数据集格式未定义 | `tests/fixtures/path_eval.json`：`{"cases":[{"name","files":{path:content},"hint":{},"expect_verdict","expect_cwe"}]}`。 |
| C3 | P1-9 “源码切片入口”未定义交互 | 抽屉节点行提供 `查看源码`，调用现有 `/source` 并展示 40 行。 |
| C4 | P1-17 包折叠“展开包”语义不清 | 点击包节点即关闭聚合并按该包目录设置 `search` 过滤；不新增路由。 |
| C5 | P1-18 清理镜像可能误删用户镜像 | 只删除 tag 前缀 `codesentry-target-` 且无容器引用；默认 `clean_images=false`。 |
| C6 | Browser smoke 如果 Safari 自动化未开启 | 脚本先 `safaridriver --enable` 提示；失败输出 `BLOCKED` 与 stderr，不伪造 PASS。 |

## D. 与既有约束一致性

- 图/Agent 主导/RAG 工具化/多租户不做：一致。
- PoC 仍默认 `off`，远程 target 不支持：一致。
- 不新增第三方 cron/通知依赖，使用 stdlib + httpx：一致。
- 不修改 AGPL `CodeScan-Artex/`：一致。

## E. 审计结论

Spec 在补齐 A1-A4、B1-B10 后可进入 plan。Plan 必须逐项给出文件、签名、测试与验收，且把 A 类放在第一批任务。
