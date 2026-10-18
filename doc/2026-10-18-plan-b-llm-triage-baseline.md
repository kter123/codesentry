# CodeSentry 方案B：LLM 通道接入实测 + Triage 降噪验证 = Spec v1.0

> **§0 步骤 1–3 已走**（范围确认/写 spec/对照 agent.md 审计——LLM 抽象 D5「用户自配厂商/本地 vLLM」+ 温度 0（D14）+ Triage 验证降噪 FR-4/成功标准 3「误报降≥50% 零漏报」全部对齐，无越界。审计结论：通过）
> **需求源：** agent.md v1.5

**目标：** 把 DeepSeek（OpenAI 兼容）接入 LLMClient 真跑 Triage/PoC 链路，验证「engine findings → LLM 验证 → 降噪输出」端到端有效，并实测降噪率基线。

**架构：** 不新增表结构。生成本机样例玫瑰仓（含已知真漏洞 + 已知误报组合），跑 `scan` 端到端（真 LLM），统计 Triage 前后 finding 数变化与误报降噪率，落 `doc/m4-triage-baseline.md`（成功标准 3 的首回测）。

**技术栈：** DeepSeek API（deepseek-chat，温度 0）；pytest live 标记隔离（live 测试显式 `-m live` 调用，默认 CI skip——网络依赖）

## 全局约束
- 平台不预置任何厂商 key；`.env` 只在本机（已写入 .gitignore 深 .env 已存在），仓库只见 `.env.example` 占位
- 温度 0（D14）；LLM 失败 → 退避 3 次 → finding 标「未验证」保留（§10）
- 比测样本：真漏洞应保留（零漏报），显式误报（如安全编码的正确使用被规则命中）应被降/否
- 误报率基线文档进 doc/（§9 M4 前哨）

## 审查重点
1. **真漏洞漏报**（比误报更严重）——样例仓含 3 个显式真漏洞，Triage 后必须全部保留
2. **LLM 输出不可解析静默成 keep**——不可解析时 confidence 必须 ≤0.4 并标注「未验证」（已有）+ 文档化
3. **live 测试污染 CI**——`@pytest.mark.live` + 默认 deselect
4. **key 泄漏**——live 测试 llama key 走环境；任何 log/print 不得超过 key 前缀 8 字符

## 任务
1. pytest.ini 加 live marker + addopts 兼容；live 测试基类化
2. 三样例：a) 真漏洞仓（SSRF 真洞）；b) 显式误报仓（规则触但不可达——如 `requests.get("https://api.hardcoded.com")` 字面量 URL）；c) 混仓（真1+误2）
3. `doc/m4-triage-baseline.md` 记录：前/后 finding 数、降噪率、漏报数（应 0）、耗时/费用
4. 收尾（ruff/mypy/license/全测/push）

## 验收
- live 全链跑通；真漏洞 3/3 保留（零漏报）；误报在样例 b/c 上 >50% 被降/否（达标记 ✅ 未达标记实测值+分析）
- `doc/m4-triage-baseline.md` 落地，agent.md §14 表 M4 行注记基线数据来源
