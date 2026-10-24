# CodeQL 引擎能力优化 · 实现计划

- 规格：`doc/2026-10-25-codeql-integration-spec.md`
- 本次范围：**P1 引擎能力**（WebUI 为 P2，不在本次实现）
- 环境实测：CodeQL 2.27.2；packs 在 `~/.codeql/packages`；Java `--build-mode=none` 可用

## 全局约束

- 不下载 CodeQL/packs；只用本机。
- OSS Gate 不变；闭源禁用 CodeQL。
- 失败降级，不阻塞扫描。
- 默认 `build-mode=none`；`manual` 才执行 build_command。

---

## 任务 1：配置解析

**文件**
- 修改：`config.py`
- 创建：`control/engine_config.py`
- 测试：`tests/test_codeql_config.py`

**接口**
```python
@dataclass
class CodeQLConfig:
    binary: str
    search_path: str
    suite: str          # 已按语言解析
    build_mode: str
    build_command: str
    timeout_s: int
    cache: bool

def resolve_codeql_config(lang: str) -> CodeQLConfig
```
- [ ] 探测顺序：DB app_settings → env → `shutil.which("codeql")` → `~/.codesentry/tools/codeql/codeql`。
- [ ] `search_path` 默认 `~/.codeql/packages`（存在时）。
- [ ] `suite` 默认 `codeql/<lang>-queries:codeql-suites/<lang>-security-extended.qls`；java/python/js/go/cpp 映射。
- [ ] 配置字段：`codeql_search_path/codeql_suite/codeql_build_mode/codeql_build_command/codeql_timeout_s/codeql_db_cache`。
- [ ] 测试：显式配置优先；PATH 回退；无 binary 返回空。

## 任务 2：引擎执行

**文件**
- 修改：`engines/codeql.py`
- 测试：`tests/test_codeql_engine.py`

- [ ] 用 `resolve_codeql_config(lang)`。
- [ ] `database create` 命令：`--build-mode`、`--source-root`、`--search-path`、`--overwrite`（cache=false）。
- [ ] cache=true：db 目录 `<work>/codeql-db/<repo_sha>-<lang>`；存在则跳过 create。
- [ ] manual 模式执行 `build_command`（cwd=repo）。
- [ ] `database analyze`：`--search-path` + suite。
- [ ] 错误分类：binary/packs 缺失 → unavailable；退出码非 0 → crashed（带 stderr 尾部）。
- [ ] 单测：mock subprocess 断言命令包含 suite/search-path/build-mode。

## 任务 3：scan 与图

**文件**
- 修改：`agents/scan.py`
- 测试：`tests/test_scan_capabilities.py`

- [ ] OSS=true 时引擎选择包含 CodeQL（现有 Gate）。
- [ ] CodeQL 成功后调用 `codeql_graph.run_codeql_graph(sarif, repo, project)`。
- [ ] `graph_delta.engine_graph.codeql` 写统计/错误。
- [ ] 测试：mock SARIF → dataflow 边计数。

## 任务 4：真实验证

- [ ] 合成 Java 仓库（Runtime.exec）`oss=true`：CodeQL 跑通、SARIF 有结果/元数据。
- [ ] 检查 `graph_edges` 中 provenance=codeql 的 dataflow。
- [ ] 全量测试、ruff、mypy。
- [ ] 两轮 review + 文档。

## 任务 5（P2，暂缓）

- WebUI 设置页、健康状态、测试按钮。本次只预留 API/字段，不实现页面。

## 审查重点

1. CodeQL 不可用时是否降级而不是报错。
2. cache 命中是否跳过 create 且不误用旧库。
3. build_command 只在 manual 执行。
4. SARIF 路径是否与 scan 的 graph adapter 一致。
5. suite/search-path 是否正确传给 create/analyze。
