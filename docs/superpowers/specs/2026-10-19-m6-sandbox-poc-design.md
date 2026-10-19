# CodeSentry M6 设计规格：沙箱部署 + PoC 实证验证 + 审查链 + 置信度校准

> 日期：2026-10-19。上游：用户需求 5 点（沙箱 docker 部署 / PoC 拿 shell 需验证 / PoC 反向查 agent 工作流 / LLM 置信度设计 / 顺带修复 SPA 白屏——已修并含回归测试）。

## 一、DeployAgent（§10 沙箱部署）

**图编排**：recon → scan → retrieval → triage → **deploy** → poc_gen → human_review → report（第七节点；LangGraph 加节点+边）。

**行为**：
1. 语言探测（复用 detect_languages）→ 取部署配方（deploy_recipes 内置 dict，v1 不做 skill）
   - python: requirements.txt 存在→`pip install -r`；入口探测（manage.py/app.py/+uvicorn|gunicorn|flask 字样）→ 起服务；探测失败 → 静态 HTTP 备胎（`python -m http.server`）仅用于文件宿主，不标记 ready
   - php: `php -S 0.0.0.0:8080 -t {root}`（composer 非必需）
   - javascript: package.json 存在 → `npm ci --omit=dev`（超 120s 跳过）→ `npm start`；无入口 → 降级
   - java: pom.xml → `mvn -q package -DskipTests`（预算 300s，超时降级 disabled）→ 找可执行 jar 起
   - go/c: 无通用服务模型 → disabled（记录原因）
2. Dokcer 执行：`docker` SDK；容器名 `codesentry-target-{scan_id}`；资源限额 cpu=1, mem=512m；网络 `codesentry-net-{scan_id}`（独立 bridge）；端口宿主随机映射
3. 健康探测：HTTP GET /，200 → ready；60s 未 ready → degraded（服务未起，仍保留静态 finding 链）
4. 失败/容器不可用：deploy_status='disabled' + 落因 → 链路继续（PoC 只能 static 档）

**Budget**：部署时长计入 node_run；max 部署秒数可配（CODESENTRY_DEPLOY_TIMEOUT_S 默认 120）
**gating 联动**：`poc_run=off`（默认）时 DeployAgent 只构建不启动服务（deplooy_status='built'）——遵守 D28/D32。

**Schema**：`scans` ADD COLUMN `deploy_status TEXT DEFAULT ''`, `deploy_log TEXT DEFAULT ''`, `target_url TEXT DEFAULT ''`

## 二、PoC 实证验证（shell → canary）

**原则**：「verified」必须附实证记录，LLM 自述不算。

验证协议（PoCAgent 升级）：
1. **canary 命令回显**：RCE/命令注入 PoC 注入 `echo CODESENTRY-{nonce}`；执行输出含 nonce → confirmed（强）
2. **HTTP 反连**：宿主一次性 listener（127.0.0.1 随机端口，路径 `/{nonce}`）；SSRF/外连类 PoC 让目标请求 listener → 命中 confirmed
3. **文件副作用**：`touch /tmp/{nonce}` 后 docker exec 检查文件存在 → confirmed
4. 以上不可用（无 target/网络禁）→ plausible（协议通但不实证）；PoC 无法执行 → rejected

**执行安全**：所有 PoC 执行只在 sandbox（docker exec codesentry-target-{scan_id}）或 target 模式容器内；宿主不留目标进程；listener 仅绑 127.0.0.1 且扫描结束即关。

**Schema**：`findings` ADD COLUMN `verification_method TEXT DEFAULT ''`（canary|listener|fs-effect|none）, `verification_nonce TEXT DEFAULT ''`

## 三、Agent Artifacts 审查链（反向追溯）

**表**：`agent_artifacts(id, scan_id, node SEQ, seq, input_digest CHAR64, input_preview TEXT(≤4KB), output_preview TEXT(≤4KB), model TEXT, tokens INT, prev_sha256 CHAR64, created_at)`

**写入点**：`graph._wrap` 外再包一层 artifact 捕获——input=state 里与本节点相关的关键摘要（triage: finding+evidence 头 2KB；poc_gen: kep findings+deploy target；retrieval: findings 清单），output=node update 头 2KB。`prev_sha256=上一 artifact output_digest`（链式哈希，防篡改可校验）。

**UI**：/review/:id “PoC 审查链” tab：选中 finding → 纵向链（report ← poc_gen ← triage ← retrieval ← scan ← deploy ← recon），每节点卡：状态/时长/tokens/模型/生效skills@version；点开看 input_preview/output_preview 全文；顶部「哈希链校验」按钮校验 prev_sha256 连贯性。

## 四、LLM 置信度（校准）

**四层模型**：`final = verdict_gated( min( raw, evidence, calibrated ) )`
1. raw：LLM 自报
2. evidence：证据切片相似度（bge-m3 余弦 ≥0.5 计满）+ 污点 BFS 实链存在 = +；仅断言 = −0.2
3. calibrated：温度缩放逻辑回归，拟合数据 = BMJ 抽样 + 自建样例 + 历史人工复核结果；参数存 `calibration_params(fit_at, a, b)` 表；每次 M4 bench 后重拟合
4. verdict_gated：confirmed=1.0、rejected=0.1、否则 raw

**UI**：confidence badge 四值分解 tooltip；队列/审阅列表按 calibrated 排序。
**验收**：M4 数据集 ECE ≤ 0.1（校准前基线也记录）。

## 五、Schema 汇总（M6 新增）

```sql
ALTER TABLE scans ADD COLUMN IF NOT EXISTS deploy_status TEXT NOT NULL DEFAULT '';
ALTER TABLE scans ADD COLUMN IF NOT EXISTS deploy_log TEXT NOT NULL DEFAULT '';
ALTER TABLE scans ADD COLUMN IF NOT EXISTS target_url TEXT NOT NULL DEFAULT '';
ALTER TABLE findings ADD COLUMN IF NOT EXISTS verification_method TEXT NOT NULL DEFAULT '';
ALTER TABLE findings ADD COLUMN IF NOT EXISTS verification_nonce TEXT NOT NULL DEFAULT '';
CREATE TABLE agent_artifacts(...); -- 如 §三
CREATE TABLE calibration_params(id, fit_at TIMESTAMPTZ, a REAL, b REAL, ece REAL);
```

## 六、里程碑

- M6.1 DeployAgent + docker 沙箱（含三条 scans 列）；验收：UI 上传含 requirements.txt+app.py 的 zip，deploy_status=ready，target_url 非空（poc_run=off 时=built）
- M6.2 PoC canary 验证（三协议）；验收：自建 RCE 样例 → verified=confirmed 且 execution_log 含 canary 命中行
- M6.3 artifacts + 审查链 UI；验收：任意 confirmed finding 可展开全链 prompt/output 预览，哈希校验通过
- M6.4 置信度校准；验收：拟合后 M4 集 ECE 数字入报告，UI badge 四分量
