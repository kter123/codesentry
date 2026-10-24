# CodeQL 接入系统与 WebUI · 设计规格

- 日期：2026-10-25
- 状态：待 spec 审计
- 实施优先级：**P1 引擎能力（先做）→ P2 WebUI 接入（后做）**
- 关联：`doc/2026-10-24-engine-dataflow-graph-spec.md`

## 0. 现状（已勘察）

- CodeQL CLI：`/Users/kking/.codesentry/tools/codeql/codeql`，版本 2.27.2。
- Query packs：`/Users/kking/.codeql/packages`，含 java/python/javascript/go/cpp/csharp/ruby。
- Java 支持 `--build-mode=none`，离线 `database create` + `database analyze` 实测成功（SARIF 产出）。
- 当前系统问题：
  - `config.codeql_bin` 默认 `"codeql"`，PATH 找不到；未自动探测。
  - engine 的 suite 参数是 `codeql-suites/java-security-extended.qls`，缺少 pack 前缀与 `--search-path`。
  - 未传 `--build-mode`；Java 闭源/无构建工具场景会失败或走 autobuild。
  - WebUI 无 CodeQL 配置/状态；`/api/health` 只 `shutil.which("codeql")`。
  - CodeQL 生成的 SARIF 已有 `codeql_graph.py` 解析 codeFlows，但 scan 只有实际跑 CodeQL 时才会用。

## 1. 目标

### P1（先做，本次验收）

- 自动发现 CodeQL CLI 与本地 packs；`--build-mode=none` 离线建库。
- suite/search-path/build-mode/build-command/timeout 可配。
- CodeQL SARIF 生成 + codeFlows 入图。
- 失败降级，不影响其他引擎。

### P2（后做）

- WebUI 设置页、引擎状态、测试按钮。
- `/api/health` 返回版本/packs。
- 扫描详情展示 CodeQL SARIF/dataflow 统计。

### 1.1 总体目标

- 扫描按 OSS Gate 使用 CodeQL；`--build-mode=none/autobuild/manual` 可配。
- CodeQL SARIF 的 codeFlows 自动入图，供路径审计。
- 失败降级：CodeQL 不可用时不影响 Semgrep/Joern 与报告。

## 2. 配置模型

| 配置 | 默认 | 说明 |
|---|---|---|
| `codeql_bin` | 自动探测 | 显式 binary 优先 |
| `codeql_search_path` | `~/.codeql/packages` | packs 搜索路径 |
| `codeql_suite` | 按语言 | 如 `codeql/java-queries:codeql-suites/java-security-extended.qls` |
| `codeql_build_mode` | `none` | `none/autobuild/manual` |
| `codeql_build_command` | 空 | manual 时的构建命令（如 `mvn -q -DskipTests package`） |
| `codeql_timeout_s` | 1800 | 建库+分析超时 |
| `codeql_db_cache` | true | 同仓库复用数据库（按 repo_hash） |

探测顺序：显式配置（DB/app_settings）→ 环境变量 → `shutil.which("codeql")` → `~/.codesentry/tools/codeql/codeql`。

## 3. 引擎执行

```
database create <db> --language=<lang> --build-mode=<mode>
  --source-root <repo> --search-path <packs> --overwrite
[optional --command <build_command>]  # build-mode=manual
database analyze <db> --format=sarif-latest --output <sarif>
  --search-path <packs> <suite>
```

- Java/Python/JS 默认 `build-mode=none`；需要依赖/编译信息时用户可改 `autobuild/manual`。
- 数据库缓存：`~/.codesentry/codeql-db/<repo_sha>-<lang>`；`--overwrite` 可选；缓存命中时跳过 create。
- 超时/失败返回 `EngineResult(status=unavailable|crashed, reason=...)`，不阻塞扫描。
- OSS Gate 不变：仅 `license_oss=true` 允许 CodeQL。

## 4. SARIF 与图

- SARIF 固定写到 `work_dir/codeql-<lang>.sarif`。
- `codeql_graph.run_codeql_graph()` 解析 codeFlows → `dataflow` 边，provenance=`codeql`。
- scan 在 CodeQL 成功后调用；失败时记录 `engine_graph.codeql.error`。

## 5. WebUI 对接

### 5.1 全局设置新增「CodeQL 引擎」

字段：binary、search_path、suite（按语言）、build_mode、build_command、timeout、cache 开关。
按钮：保存、探测（`codeql version` + `resolve packs` + 语言列表）。

### 5.2 状态展示

- `/api/health` 的 engines：`codeql` 返回 `{found, version, search_path, packs: [...]}`，不再只是路径字符串。
- Overview 引擎状态显示 CodeQL 版本/packs 是否存在。
- 扫描详情 engine meta 展示 CodeQL 是否运行、SARIF 路径、dataflow 边数。

### 5.3 API

| 端点 | 说明 |
|---|---|
| `GET /api/settings/codeql` | 配置（脱敏；无密钥） |
| `PUT /api/settings/codeql` | 保存 |
| `POST /api/engines/codeql/test` | 版本 + packs + 可选建库小样 |

## 6. 安全

- 平台不内置/分发 CodeQL binary 或官方规则包；只用用户本机安装。
- build_command 只在用户目标仓库内执行；WebUI 明确提示风险，默认 `none`。
- 不访问外网；packs 必须本地存在。

## 7. 验收

1. `GET /api/health` 返回 CodeQL 2.27.2、packs 列表。
2. 合成 Java 仓库 `oss=true` 扫描：CodeQL 运行、SARIF 生成、`codeql` dataflow 边入图。
3. WebUI 设置页可保存/探测 CodeQL；错误路径显示不可用。
4. `build-mode=none` Java 建库成功；`manual` 配置 build_command 时执行。
5. 全量测试绿。

## 8. 非目标

- 不自动下载/更新 CodeQL 或 packs。
- 不做远程 CodeQL 执行。
- 不保证所有语言 suite 存在；缺失时明确报错。
