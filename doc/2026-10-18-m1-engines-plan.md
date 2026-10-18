# CodeSentry M1（引擎集成）实现计划 = Spec v1.0

> **面向 AI 代理的工作者：** 必需子技能：使用 subagent-driven-development（推荐）或 executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。
>
> - **spec 审计结论（§0 流水线第 3 步）：** 已审计（2026-10-18）。逐项对照 agent.md v1.4：M1 范围（三引擎并行调度 + 许可 Gate + §4.2 覆盖矩阵逐组合验证 + 统一 Finding 模型 + SARIF 导出）全覆盖；数值与红线逐条照抄一致；无越界（M3 的 LangGraph 编排 / M2 的 RAG 不涉及）。审计结论：**通过**。
> - **需求源：** 根目录 `agent.md` v1.4（SSOT，D1–D38）

**目标：** 三引擎真实集成——统一 Finding 模型、许可 Gate（闭源禁 CodeQL）、并行双引擎调度、SARIF 2.1.0 导出、六语言样例仓 + 覆盖矩阵逐组合验证，并在扫描元数据标注降级。

**架构：** 不引入 LangGraph（M3 才引入）。M1 是「多模块函数库 + CLI 落点」：`scan` 命令从占位变真实现，驱动 recon(极简) → engines(并行子进程) → normalize → sarif/markdown 报告。引擎各以独立模块封装子进程调用与私有格式解析，归一层统一为 `Finding`（pydantic）。并行用 `concurrent.futures.ThreadPoolExecutor`（子进程 IO bound，线程足够，无需 M3 前置编排）。

**技术栈：** 复用 M0 底座（uv/typer/pydantic/pydantic-settings/psycopg）；新增 pydantic（已有传递依赖，显式声明）；样例仓用 git 子目录仓（非 submodule，纯文件）。
**规格：** `agent.md`（根目录）

---

## 全局约束（自 agent.md 逐条）

- 三引擎并行双组合：开源 CodeQL+Semgrep；闭源 Joern+Semgrep（D8）；单引擎超时/崩溃互为降级不阻塞，三引擎全失败中止落因（§10）
- 许可 Gate（FR-3）：仅 `--oss` 时启用 CodeQL；ScanAgent 强制；声明落库可审计；平台不分发 CodeQL，仅探测 `CODESENTRY_CODEQL_BIN`（§3）
- 语言矩阵（§4.2/§2.1）：Python/Java/JS-TS/Go/C-C++/PHP 六门；PHP 无 CodeQL；pysrc2cpg/gosrc2cpg/php2cpg 前端 M1 实测
- 每个语言×引擎组合至少 1 个可运行验证样例；不可用组合显式降级写进扫描报告元数据
- SARIF 2.1.0（FR-6）：含严重度/置信度/证据行号；taxa 用 CWE
- Finding 归一（FR-2）：CWE、source/sink、置信度初值
- Java 源码级分析（D15），M1 不做构建
- CodeQL 趋势：CLI 缺失时该引擎结果为「不可用」而非报错（§10 互为降级）
- 测试：Finding 归一化单测；许可 Gate 单测（闭源声明时禁用 CodeQL）；六语言小型样例仓端到端测试（§10）
- `--skills` 仍占位（M3 生效）；db 表（scans/findings）留 M3 落表——M1 报告纯文件产物，不入库（避免半成品表）

## 审查重点（Review Focus）

1. **闭源仓库误启 CodeQL**——Gate 必须在「调度前」由独立函数强制（单元测试钉死）；不允许仅靠 CLI 分支
2. **引擎子进程超时挂死主流程**——所有子进程调用带 timeout（默认引擎层 3600s，env 覆写），超时→该引擎结果标「超时」并继续另一引擎
3. **SARIF 输出非法 schema**——导出后用 `json` 结构断言（version=2.1.0/$schema/invocations[0]），发布样例对比官方模板
4. **样例仓演成巨型 fixture 泄漏仓库大小**——样例仓单个文件< 100 行，总体积<100KB，放 `examples/`，`.gitignore` 排除构建产物
5. **stderr 拼进 stdout 解析**——引擎子进程分开 `capture`，解析仅用 stdout，stderr 独立记录进引擎结果元数据

---

## 文件结构

```
src/codesentry/
├── models.py               # Finding / ScanProfile / EngineResult / LicenseDeclaration (pydantic)
├── engines/
│   ├── __init__.py          # run_engine 调度入口
│   ├── base.py              # 子进程公共封装（timeout、stdout/stderr 分离）
│   ├── codeql.py            # 探测 + 构建 + 查询；Gate 拒绝时返回 unavailable
│   ├── joern.py             # CPG 生成 + 数据流查询（自研迁移：M1 先用查询产出 alert json）
│   ├── semgrep.py           # --json 解析
│   └── normalize.py         # 引擎私有条目 → Finding
├── reportex/
│   ├── __init__.py
│   ├── sarif.py             # Finding list → SARIF 2.1.0 dict + 写盘
│   └── markdown.py          # Finding list → 中文 Markdown 报告
├── scan_orchestrator.py     # scan 主流程（recon 极简 + Gate + 并行调度 + 归一 + 报告）
examples/                    # 各语言样例仓（新增，git 跟踪）
├── python/ssrf_flask/
├── java/path_traversal_file/
├── javascript/proto_pollution_gadget/
├── go/util_injection_exec/
├── c/format_string_printf/
└── php/stack_trace_disclosure/
tests/
├── test_models.py
├── test_gate.py
├── test_engines_base.py
├── test_normalize.py
├── test_sarif.py
├── test_markdown.py
├── test_scan_cli.py         # CLI scan 集成（mock 引擎）
├── test_examples_matrix.py  # 六语言×引擎组合逐个实跑（engine-installed skip 适配）
└── fixtures/…               # 引擎输出的最小片段样例
```

---

### 任务 1：统一模型（TDD）

**文件：** 创建 `src/codesentry/models.py`；测试 `tests/test_models.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_models.py
import pytest
from pydantic import ValidationError

from codesentry.models import EngineResult, Finding, LicenseDeclaration, ScanProfile


def test_finding_minimal():
    f = Finding(
        rule_id="py/宏伟", cwe=918, severity="high", confidence=0.7,
        file="a.py", line=10, message="SSRF sink", engine="semgrep",
    )
    assert f.cwe == 918 and f.engine == "semgrep"


def test_finding_severity_enum():
    with pytest.raises(ValidationError):
        Finding(rule_id="x", cwe=79, severity="catastrophe", confidence=0.5,
                file="a", line=1, message="m", engine="semgrep")


def test_finding_optional_fields():
    f = Finding(rule_id="x", cwe=79, severity="low", confidence=0.5,
                file="a", line=1, message="m", engine="joern",
                end_line=5, taint_metadata={"source": "input()"})
    assert f.end_line == 5


def test_license_declaration():
    d = LicenseDeclaration(OSS=True, declared_at="2026-10-18T00:00:00Z")
    assert d.OSS is True


def test_engine_result_degraded():
    r = EngineResult(engine="codeql", status="unavailable", reason="license gate")
    assert r.status == "unavailable" and r.findings == []
```

- [ ] **步骤 2：运行测试验证失败**
- [ ] **步骤 3：实现模型**——`severity: Literal["info","low","medium","high","critical"]`；`confidence: float` 0–1；`engine: Literal["codeql","joern","semgrep"]`；`LicenseDeclaration(OSS: bool, declared_at: str)`；`ScanProfile(languages: list[str], frameworks: list[str], entry_points: list[str])`；`EngineResult(engine, status: Literal["ok","timeout","crashed","unavailable"], findings=[], reason="")`
- [ ] **步骤 4：运行测试通过** `uv run pytest tests/test_models.py -v`
- [ ] **步骤 5：Commit** `feat(m1): unified Finding/EngineResult/LicenseDeclaration models (FR-2)`

### 任务 2：许可 Gate（TDD）

**文件：** 创建 `src/codesentry/gate.py`；测试 `tests/test_gate.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_gate.py
from codesentry.gate import LicenseGate


def test_closed_source_blocks_codeql():
    g = LicenseGate(OSS=False)
    allowed, reason = g.check_engine("codeql")
    assert not allowed
    assert "license" in reason.lower() or "闭源" in reason


def test_oss_allows_codeql():
    g = LicenseGate(OSS=True)
    allowed, _ = g.check_engine("codeql")
    assert allowed


def test_any_engine_unrestricted():
    for engine in ("joern", "semgrep"):
        assert LicenseGate(OSS=False).check_engine(engine)[0] is True
```

- [ ] **步骤 2：运行测试验证失败**
- [ ] **步骤 3：实现**——`LicenseGate(OSS: bool).check_engine(engine) -> tuple[bool, str]`；闭源 + codeql → `(False, "…")`；其余 `(True, "")`。Gate 与下发声明记录函数分开：`record_declaration(scan_id, decl)` M3 连库时接，M1 返回 dict
- [ ] **步骤 4：运行通过**
- [ ] **步骤 5：Commit** `feat(m1): license gate — closed-source blocks CodeQL (FR-3)`

### 任务 3：引擎子进程基础封装（TDD）

**文件：** 创建 `src/codesentry/engines/base.py`、`__init__.py`；测试 `tests/test_engines_base.py`

- [ ] **步骤 1：测试**

```python
# tests/test_engines_base.py
import subprocess

import pytest

from codesentry.engines.base import run_subprocess


def test_run_success():
    r = run_subprocess(["python3", "-c", "print('hi')"], timeout=10)
    assert r.ok and r.stdout.strip() == "hi"


def test_run_timeout_marks_added():
    r = run_subprocess(["python3", "-c", "import time; time.sleep(5)"], timeout=1)
    assert not r.ok and "timeout" in r.reason.lower()


def test_run_bad_binary():
    r = run_subprocess(["codesentry-nonexistent-bin-_xyz"], timeout=5)
    assert not r.ok and ("not found" in r.reason.lower() or "enoent" in r.reason.lower())


def test_stderr_not_in_stdout():
    r = run_subprocess(
        ["python3", "-c", "import sys; print('out'); sys.stderr.write('err')"], timeout=10
    )
    assert "out" in r.stdout and "out" not in r.stderr
```

- [ ] **步骤 2：失败确认**
- [ ] **步骤 3：实现 base.py**——`@dataclass SubprocResult(ok, stdout, stderr, reason, exit_code, timeout_used)`；`run_subprocess(cmd, timeout, cwd=None)`：`subprocess.run` 带超时；`FileNotFoundError` → `reason=…not found`；`TimeoutExpired` → `reason="timeout after {n}s"`，行为不抛
- [ ] **步骤 4：通过**
- [ ] **步骤 5：Commit** `feat(m1): engine subprocess base — timeout + stdout/stderr separated`

### 任务 4：三引擎模块 + 归一（TDD，mock 为主 + 真跑安全样例）

**文件：** 创建 `engines/semgrep.py`、`engines/normalize.py`；测试 `tests/test_normalize.py` + `tests/fixtures/semgrep_sample.json`

- [ ] **步骤 1：测试（semgrep 归一）**

```python
# tests/test_normalize.py
import json, pathlib
from codesentry.engines.normalize import normalize_semgrep

FIXTURE = json.loads((pathlib.Path(__file__).parent / "fixtures" / "semgrep_sample.json").read_text())


def test_normalize_semgrep_finding_fields():
    fs = normalize_semgrep(FIXTURE)
    assert len(fs) >= 1
    f = fs[0]
    assert f.engine == "semgrep"
    assert f.severity in ("info", "low", "medium", "high", "critical")
    assert 0.0 <= f.confidence <= 1.0
    assert f.file and f.line >= 1


def test_severity_mapping():
    fs = normalize_semgrep(FIXTURE)
    by_sev = {f.rule_id: f.severity for f in fs}
    assert by_sev.get("test-rule-low") == "low"
    assert by_sev.get("test-rule-high") == "high"
```

`fixtures/semgrep_sample.json`（官方 `--json` 输出 schema 最小样例）：

```json
{
  "results": [
    {"check_id": "test-rule-low",
     "path": "app.py",
     "start": {"line": 10},
     "end": {"line": 12},
     "extra": {
       "message": "matches rule low",
       "severity": "WARNING",
       "metadata": {"cwe": "CWE-918: Server-Side Request Forgery"}
     }},
    {"check_id": "test-rule-high",
     "path": "app.py",
     "start": {"line": 20},
     "extra": {"message": "matches rule high",
               "severity": "ERROR",
               "metadata": {"cwe": "CWE-78: OS Command Injection"}}}
  ]
}
```

- [ ] 步骤 2 失败确认 → 步骤 3 实现 normalize.py：severity 映射 `ERROR→high / WARNING→medium / INFO→low`；confidence 初值 per engine（semgrep 0.5，codeql 0.7，joern 0.7）；CWE 从 `metadata.cwe` 提取 `CWE-(\d+)`，无 fallback 610（CWE-610=映射缺失显式标注）；步骤 4 通过 → 步骤 5 `feat(m1): semgrep engine + finding normalization`

### 任务 5：Joern/CodeQL 骨架 + errorsafe（低耦合，无需真引擎也能测）

**文件：** 创建 `engines/joern.py`、`engines/codeql.py`；测试 `tests/test_engines_skeleton.py`

- [ ] **步骤 1：测试（缺 binary 时优雅降级）**

```python
# tests/test_engines_skeleton.py
from codesentry.engines.codeql import run_codeql
from codesentry.engines.joern import run_joern


def test_codeql_missing_bin_degrades(monkeypatch, tmp_path):
    # 让 shutil.which 永远找不到
    monkeypatch.setenv("CODESENTRY_CODEQL_BIN", "codesentry-nonexistent-_xyz")
    r = run_codeql(repo=tmp_path, lang="python", OSS=True, out_dir=tmp_path)
    assert r.status == "unavailable"
    assert "not found" in (r.reason or "").lower()


def test_joern_missing_bin_degrades(monkeypatch, tmp_path):
    monkeypatch.setenv("CODESENTRY_JOERN_BIN", "codesentry-nonexistent-_xyz")
    r = run_joern(repo=tmp_path, lang="python", out_dir=tmp_path)
    assert r.status == "unavailable"
```

- [ ] 步骤 2 失败 → 步骤 3：实现 `run_joern(repo, lang, out_dir, timeout=3600)` / `run_codeql(repo, lang, OSS, out_dir)`——先 `shutil.which` 探测，缺失/空仓 → `status="unavailable"`；binary 存在时构建真实调用链（joern-parse → joern 查询脚本 → alert json；codeql db create → codeql database analyze），解析产出 EngineResult。M1 对 joern 查询语言实现只保 6 个最小污染查询（6 语言各 1 sink 类）——**注**：真实数据流深度查询 M1 以「joern 内置 alert 输出（--security probes）」+自研脚本起步，M3 深化。步骤 4/5 通过 + `feat(m1): joern/codeql engine modules with graceful degradation`

### 任务 6：引擎并行调度（TDD）

**文件：** 创建 `src/codesentry/scan_orchestrator.py`；测试 `tests/test_scan_orchestrator.py`

- [ ] **步骤 1：测试**

```python
# tests/test_scan_orchestrator.py
from codesentry.models import EngineResult, Finding
from codesentry.scan_orchestrator import run_engines_parallel


def test_parallel_two_engines():
    def fake_a(**kw):
        return EngineResult(engine="joern", status="ok",
                            findings=[Finding(rule_id="j1", cwe=79, severity="medium",
                                              confidence=0.7, file="a", line=1,
                                              message="m", engine="joern")])
    def fake_b(**kw):
        return EngineResult(engine="semgrep", status="ok", findings=[])
    results = run_engines_parallel(specs=[fake_a, fake_b])
    assert [r.engine for r in results] == ["joern", "semgrep"]


def test_one_crash_does_not_block_other():
    def fake_a(**kw):
        raise RuntimeError("boom")
    def fake_b(**kw):
        return EngineResult(engine="semgrep", status="ok", findings=[])
    results = run_engines_parallel(specs=[fake_a, fake_b])
    assert len(results) == 2
    statuses = {r.engine: r.status for r in results}
    assert statuses.get("semgrep") == "ok"
    assert any(s in ("crashed", "timeout") for s in statuses.values())


def test_engine_selection_by_license():
    from codesentry.scan_orchestrator import select_engines
    oss, prop = select_engines(OSS=True), select_engines(OSS=False)
    assert "codeql" in oss and "codeql" not in prop
    assert "semgrep" in oss and "semgrep" in prop
```

- [ ] 步骤 2 失败 → 步骤 3 实现：`select_engines(OSS: bool) -> list[str]`（开源 ["codeql","semgrep"]；闭源 ["joern","semgrep"]，PHP 时 ["joern","semgrep"] 无论 OSS——§4.2 PHP 无 CodeQL）；`run_engines_parallel(specs)` 用 ThreadPoolExecutor(max_workers=2)，单个 callable 抛异常捕获→ `EngineResult(engine=名字, status="crashed", reason=…)`；全部 crashed → 上层中止落因（orchestrator 返回值由 scan 流程判断）
- [ ] 步骤 4/5 → `feat(m1): parallel engine dispatch with per-engine degradation (D8, §10)`

### 任务 7：SARIF 导出（TDD）

**文件：** 创建 `reportex/sarif.py`、`__init__.py`；测试 `tests/test_sarif.py`

- [ ] **步骤 1：测试**

```python
# tests/test_sarif.py
import json
from codesentry.models import Finding
from codesentry.reportex.sarif import findings_to_sarif


def _f(**kw):
    base = dict(rule_id="py/ssrf", cwe=918, severity="high", confidence=0.7,
                file="a.py", line=10, message="SSRF", engine="semgrep")
    base.update(kw)
    return Finding(**base)


def test_sarif_structure():
    doc = findings_to_sarif([_f()])
    assert doc["version"] == "2.1.0"
    assert "$schema" in doc
    run = doc["runs"][0]
    assert run["tool"]["driver"]["name"] == "CodeSentry"
    assert len(run["results"]) == 1
    res = run["results"][0]
    assert res["ruleId"] == "py/ssrf"
    assert res["level"] in ("warning", "error", "note")
    assert res["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "a.py"
    assert res["locations"][0]["physicalLocation"]["region"]["startLine"] == 10


def test_sarif_cwe_taxa():
    doc = findings_to_sarif([_f()])
    taxa = doc["runs"][0]["tool"]["driver"]["supportedTaxonomies"]
    rules = doc["runs"][0]["tool"]["driver"]["rules"]
    assert any(r["id"] == "py/ssrf" for r in rules)


def test_sarif_confidence_property():
    doc = findings_to_sarif([_f(confidence=0.9)])
    res = doc["runs"][0]["results"][0]
    props = res.get("properties", {})
    assert props.get("confidence") == 0.9
```

- [ ] 步骤 2 失败 → 步骤 3 实现：`findings_to_sarif(findings) -> dict`（SARIF 2.1.0 官方 schema）；`level` 映射（critical/high→error，medium→warning，low/info→note）；`properties` 携带 `confidence/severity/cwe/engine`；driver.rules 聚合；`supportedTaxonomies` 引用；`write_sarif(findings, path)`
- [ ] 步骤 4/5 → `feat(m1): SARIF 2.1.0 export with CWE taxa and confidence property (FR-6)`

### 任务 8：中文 Markdown 报告（TDD）

**文件：** 创建 `reportex/markdown.py`；测试 `tests/test_markdown.py`

- [ ] **步骤 1：测试**

```python
# tests/test_markdown.py
from codesentry.models import Finding
from codesentry.reportex.markdown import render_markdown


def _f(**kw):
    base = dict(rule_id="py/ssrf", cwe=918, severity="high", confidence=0.7,
                file="a.py", line=10, message="SSRF sink", engine="semgrep")
    base.update(kw)
    return Finding(**base)


def test_markdown_contains_sections():
    md = render_markdown([_f()], profile_languages=["python"])
    for token in ("# CodeSentry", "python", "py/ssrf", "CWE-918", "a.py:10", "置信度"):
        assert token in md


def test_markdown_empty_findings():
    md = render_markdown([], profile_languages=["python"])
    assert "未发现" in md or "没有" in md or "空" in md
```

- [ ] 步骤 2 失败 → 步骤 3 实现：`render_markdown(findings, profile_languages, license_declaration=None) -> str`；含概览表（严重度_counts）、逐条 finding 段落（规则/CWE/严重度/置信度/文件行号/修复建议占位 M3 丰富）；空列表输出「未发现」段落，不空文件
- [ ] 步骤 4/5 → `feat(m1): Chinese markdown report (FR-6)`

### 任务 9：`scan` 命令接真（编排整条链）

**文件：** 修改 `cli_commands.py`（scan_cmd 真实现）、新增 `scan_orchestrator.py` 内 `run_scan(repo, OSS, out_dir) -> ScanOutcome`；测试 `tests/test_scan_cli.py`（mock 引擎层）

- [ ] **步骤 1：测试**

```python
# tests/test_scan_cli.py
import json
from pathlib import Path

from typer.testing import CliRunner

import codesentry.cli as cli_mod

runner = CliRunner()


def test_scan_closed_source_runs_and_writes_reports(tmp_path, monkeypatch):
    # 无引擎可用的前提下 scan 应仍然完整出报告（全 unavailable 也是输出，不是崩溃）——
    # 但三引擎全 array 不可用时按 §10 中止该扫描并落因 → 需要至少 semgrep 正常。monkeypatch semgrep 路径不存在 + joern 不存在 → 应 exit 非0
    import codesentry.scan_orchestrator as so

    def fake_run_engines(specs):
        return [EngineResult(engine="semgrep", status="ok",
                             findings=[Finding(rule_id="t/1", cwe=79, severity="low",
                                               confidence=0.5, file="x.py", line=1,
                                               message="m", engine="semgrep")])]

    monkeypatch.setattr(so, "run_engines_parallel", fake_run_engines)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "x.py").write_text("x = 1")
    out = tmp_path / "out"
    r = runner.invoke(cli_mod.app, ["scan", str(repo), "--out", str(out)])  # 无 --oss
    assert r.exit_code == 0, r.output
    files = {p.name for p in out.iterdir()}
    assert "report.sarif" in files and "report.md" in files
    sarif = json.loads((out / "report.sarif").read_text())
    assert sarif["version"] == "2.1.0"


def test_scan_pure_declares_gate_in_metadata(tmp_path, monkeypatch):
    import codesentry.scan_orchestrator as so

    captured = {}
    real = so.run_engines_parallel
    def fake_run_engines(specs):
        captured["engines"] = [getattr(s, "__name__", "?") for s in specs]
        return real(specs)
    monkeypatch.setattr(so, "run_engines_parallel", fake_run_engines)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "x.py").write_text("x = 1")
    out = tmp_path / "out"
    r = runner.invoke(cli_mod.app, ["scan", str(repo), "--out", str(out)])
    assert r.exit_code == 0, r.output
    md = (out / "report.md").read_text()
    assert "闭源" in md or "proprietary" in md
```

- [ ] 步骤 2 失败 → 步骤 3 实现 `run_scan`：profile（M0 极简——语言后缀探测 + 首文件语言推断）→ LicenseGate → select_engines → 引擎调用（可用 engine 表 dispatch）→ 归一 Finding 列表 → 报告双写。CLI `scan_cmd` 直通 `run_scan`，`--out` 默认 `<repo>/codesentry-report`。scan 元数据里记录许可声明（Markdown 头部 JSON 块）
- [ ] 步骤 4/5 → `feat(m1): scan command wired end-to-end with gate + parallel engines + reports`

### 任务 10：六语言样例仓 + 覆盖矩阵验证

**文件：** 创建 `examples/{python/ssrf_flask, java/path_traversal_file, javascript/proto_pollution_gadget, go/util_injection_exec, c/format_string_printf, php/stack_trace_disclosure}/`；测试 `tests/test_examples_matrix.py`

- [ ] **步骤 1：每个样例=3 个文件：`代码` + `README.md`（CVE 说明）+ `expected.json`（期望 CVE/CWE、最小可检出行）**。小而真（<100 行/仓）；检测点真实可触发（可运行验证）
- [ ] **步骤 2：矩阵测试**

```python
# tests/test_examples_matrix.py
"""六语言×引擎覆盖矩阵逐组合验证（agent.md §4.2）。
策略：每个组合跑 run_{engine}(examples/<lang>/)，断言找到期望 CVE 文件行号——
引擎不可用（未安装）时 pytest.skip 标注降级记录。
"""
```

对 6 语言 × {joern, semgrep}，缺失引擎 skip（并把「引擎不可用」记录写进 `doc/m1-coverage-report.md`）；codeql 组合整体 skip-if-missing（本身不分发）。
- [ ] 步骤 3 逐组合实跑记录 → 步骤 4 生成 `doc/m1-coverage-report.md`（每组合：状态/检出/耗时/降级标注）→ 步骤 5 Commit `feat(m1): six-language example repos + coverage matrix validation (NFR-1, §4.2)`

### 任务 11：收尾

- [ ] ruff/mypy 清零；全量 pytest 通过
- [ ] M1 验收核对：三引擎并行调度使兼容成组、Gate 强制、矩阵表落地、SARIF/MD 报告可用
- [ ] Commit + push（认证恢复后）

---

## 任务依赖与并发

```
任务1（模型）→ 任务2（Gate，依赖模型）→ 任务3（base）→ 任务4（semgrep 归一）→ 任务5（joern/codeql 骨架）→ 任务6（并行调度）→ 任务7/8（报告，依赖1）→ 任务9（scan 接真，依赖全部前）→ 任务10（矩阵验证）→ 任务11 收口
```

任务 1–3 可串行快速完成；7/8 可与 4–6 并行（仅依赖 1）；5 在 joern/semgrep 真实二进制到位后跑真实验证。

## 里程碑状态表（§0 第 8 步回填）

| 里程碑 | 状态 | spec | 验收记录 |
|---|---|---|---|
| M0 脚手架 | 完成 | doc/2026-10-18-m0-scaffold-plan.md | 27 tests / lint+mypy clean / compose+init-db 实证 |
| M1 引擎集成 | 本计划执行中 | 本文件 | 待回填 |
| M2–M5 | 未开始 | — | — |
