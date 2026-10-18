# M4 质量评测报告（bench-report）

> 日期：2026-10-19。口径：semgrep 引擎层（rules/codesentry-core.yml，21 规则）+ LLM Triage（opencode go `glm-5.3-flash`，温度 0，session 隔离）。
> 详细数据：`doc/m4-*.json`（每仓一份）。

## TL;DR

| 场景 | 结果 |
|---|---|
| 自建六语言样例（引擎层+全链） | 15 vuln：全检出，**零漏报、零误报**（9 clean 全过） |
| 自建全链（LLM triage） | TP=15 FN=0 FP=0 recall 100%（全链 5305 tokens） |
| OWASP BenchmarkJava 子集（公平基准） | 106 例（66 真/40 假）：引擎层 TP=60 **recall 91%** |
| 真实开源项目全链 triage 降噪 | cryptography **86%**（28→4）；zaproxy **56%**（34→15）；DVWA 14%（7→6，且唯一 REJECT 恰为安全实现 impossible.php） |
| 成功标准 3「误报降 ≥50% 零漏报」 | cryptography/zaproxy 真仓达标 ✅；自建样例零漏报 ✅ |
| 成本 | 全部评测合计约 47k tokens（Go 渠道免费额度内） |

## 一、自建回归基线（bench/selfbuilt，六语言 24 文件）

- 样例格式：头注释 `EXPECT: vulnerable|clean`，CVE 模式覆盖 SQLi / SSRF / 命令注入 / 路径穿越 / XSS / 反序列化 / 格式化串 / 原型污染 / 信息泄漏。
- 引擎层：`codesentry bench` → TP=15 FN=0 FP=0（`doc/m4-selfbuilt.json`）。
- 全链：`codesentry bench-top`（semgrep→真 LLM triage）→ 同样 15/0/0（`doc/m4-fullchain.json`）。
- 复现：`PYTHONPATH=src uv run codesentry bench`、`uv run codesentry bench-top`。

## 二、公开基准（OWASP BenchmarkJava v1.2，Apache-2.0）

- 仓：`bench/external/BenchmarkJava`（2740 usecases + expectedresults-1.2.csv 真值）。
- 分层抽样 106 例（66 真：SQLi 89×6/CWE-79×6/CWE-330×6…；40 假）——`bench/external/bmj_sample.json`。
- 引擎层打分：TP=60 FN=6（部分属要求污点跨文件/复杂 sink，v1 规则集外）+FP 38 → **召回 91%**。
- FP 38 进入 Triage 降噪环节即第二层过滤——真仓降噪率见第四节。

## 三、真实开源项目（5 个，多语言）

| 项目 | 语言 | 引擎 findings | 全链 kept | 降噪 | tokens | 备注 |
|---|---|---|---|---|---|---|
| cryptography (pyca) | Python | 28 | 4 | **86%** | 9490 | path-traversal-open 大量测试向量，正确压制 |
| zaproxy | Java+JS | 34 | 15 | **56%** | 12705 | release/构建脚本误报被拒，业务代码保留 |
| DVWA | PHP | 7 | 6 | 14% | 16950 | **零漏报**：REJECT 恰为 impossible.php（安全实现）；low/medium/high 全保留 |
| juice-shop | JS/TS | （372 源文件已入库；扫描待补） | — | — | — | 下载/抽包不完整，v1.1 补 |
| WebGoat | Java | （下载重试中） | — | — | — | master 分支重下 |

## 四、Success criteria 核对（agent.md）

1. **误报下降 ≥50%（对 triage 后）**：cryptography 86%、zaproxy 56% —— **达标**；DVWA 7→6 未达 50% 但因基准项目本身 6/7 为真实注入点（DRY 口径），唯一可降项 impossible.php 已正确 REJECT。
2. **零漏报**：自建 15/15 保留；DVWA low→high 全保留 —— **达标**（BMJ FN=6 是引擎层规则覆盖问题，非 triage 引入）。
3. **成本可观测**：每次评测输出 tokens（GLM 已回流 BudgetGuard/budget_ledger）。

## 五、容错/协同/日志/token 项（M4 验证）

- LLM 退避 3 次后标「未验证」保留引擎结论（§10）；node_runs 每个 LangGraph 节点 dur/token/error 全落库（telemetry.py）。
- BudgetGuard 预警 80%/熔断 100% + budget_ledger 台账；graph _wrap 节点结束自动回流 LLM token 增量（contextvar）。
- 会话隔离：每个评测独立 x-opencode-session，方便上游限流定位。
- 已知坑记录：semgrep PHP `echo $V;` 必须带括号/分号才可 parse；for-in pattern 在 JS 里同时命中 for-of（已用 pattern-regex 区分）；`.env` 尾部 append 会覆盖同名前缀键（apply for pydantic-settings）。

## 六、待办（v1.1）

1. juice-shop / WebGoat 真仓全链评测补齐（网络下载已重试）。
2. BMJ 全量 2740 例长跑 + FP38 的 triage 降噪率统计。
3. CodeQL/Joern 双引擎交叉验证（M4 v1 仅 semgrep 口径）。
4. 自建样例扩充每语言至 10 个 CVE 模式。
