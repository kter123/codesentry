# CodeSentry M0（脚手架）实现计划 = Spec v1.0

> **面向 AI 代理的工作者：** 必需子技能：使用 subagent-driven-development（推荐）或 executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。
>
> - **spec 审计结论（§0 流水线第 3 步）：** 已审计（2026-10-18）。逐项对照 agent.md v1.4：M0 范围六件套（目录结构 / docker-compose / 配置加载 / CLI 骨架 / `.env.example` 扩展 / license 检查脚本）全覆盖；全局约束数值逐条照抄一致；审查重点 5 项均带对应测试。**差异 2 处，均为超前实现而非矛盾，批准保留**：① agent.md §9 写"八命令占位"，计划让 `engines` 完全真实现——agent.md 本就把"探测三引擎与 JDK"列为 engines 功能本体，无越界；② `init-db` 提前真实现——M1 起所有里程碑的前置依赖，属"可运行底座"应有之义。计划中 `scan --oss` / `--skills` 仅声明旗标不实现，Gate 强制逻辑严格留在 M1 无越界。**审计结论：通过。**
> - **需求源：** 根目录 `agent.md` v1.4（SSOT，D1–D38）

**目标：** 搭建 CodeSentry 工程骨架——工程结构、docker-compose、配置系统、八命令 CLI 骨架、合规检查脚本，为 M1–M5 提供可运行底座。

**架构：** 单包 Python 项目（uv + src 布局），`codesentry` 可执行入口；PostgreSQL 16 + pgvector 单实例（业务 schema `codesentry` / checkpoint schema `langgraph`，PG 数据卷落挂载盘）；配置经 pydantic-settings 从环境变量 + `.env` 加载（前缀 `CODESENTRY_`）；CLI 用 Typer，八命令全部可运行（未实现功能给出明确"未实现"提示；`engines check` 为真实探测）。

**技术栈：** Python 3.11+ / uv / typer / rich / pydantic-settings / docker compose；license 检查脚本仅标准库。

**规格：** `agent.md`（根目录）

---

## 全局约束（自 agent.md 逐条）

- Python 3.11+；uv 管理依赖；ruff + mypy；pytest（§9）
- 红线（§3）：发行物不含 CodeQL CLI 二进制；不含官方 semgrep 规则文件；依赖逐项记录 license 并阻塞不合许可引入
- PG 单实例分 schema：业务 `codesentry` 与 checkpoint `langgraph` 分层隔离；PGDATA 绑挂载盘（§8，D18）
- 预算默认值（D14）：`max_tokens=500000`、`max_tool_calls=500`、`max_cost_usd=10`、`max_findings=200`
- `human_review=False`；`temperature=0`（D14）；`poc_run=off`（D28）；Web 绑定 `0.0.0.0`（D36）
- 平台协议 Apache-2.0（D6）；CLI 七命令外加 `skills`，共八命令（D13 + D25）
- M0 DDL 范围 = 2×CREATE SCHEMA + `CREATE EXTENSION IF NOT EXISTS vector`；全量表 DDL 从 M1 起随功能增量落（§8 表清单是全量目标清单，M0 不落表）
- M0 验收（§9）：compose 可起库、八命令可运行、license 检查脚本可跑

## 审查重点（Review Focus）

1. **`.env` 真实密钥误提交**——`.gitignore` 已就位（先前轮次已建）；本计划只创建 `.env.example`，实现中任何步骤不得触碰 `.env`
2. **compose 卷源非绝对路径/为空**——数据写进项目目录而非挂载盘；compose 用 `${CODESENTRY_PGDATA_HOST:?err}` 强制非空，`.env.example` 注释注明"必须为挂载盘绝对路径"
3. **schema 边界混乱**——业务表进 `langgraph` schema 或反之；常量、DDL、测试三处钉住 `codesentry` / `langgraph` 两个名字
4. **CLI 未知/未实现命令静默成功**——退出码 0 会污染 CI；未实现命令必须 exit 1 + 指明里程碑的提示
5. **`engines check` 假探测**——必须真实 shell out（`shutil.which` + `java -version` 探测），不得返回硬编码结果

---

## 文件结构

```
codesentry/
├── agent.md                  # SSOT（已存在，不动）
├── doc/
│   └── 2026-10-18-m0-scaffold-plan.md   # 本计划（已存在）
├── pyproject.toml            # 包定义 + 工具配置
├── LICENSE                   # Apache-2.0 全文（D6）
├── uv.lock                   # 由 uv sync 生成
├── .env.example              # 全量配置模板（重写现有）
├── docker-compose.yml        # PG16+pgvector 单实例
├── scripts/
│   └── check_licenses.py     # 合规红线检查（§3），独立可执行、仅标准库
├── src/codesentry/
│   ├── __init__.py           # __version__
│   ├── cli.py                # Typer app 组装
│   ├── cli_commands.py       # 八命令实现（薄层）
│   ├── config.py             # Settings
│   └── db/
│       ├── __init__.py
│       └── schema.py         # schema 常量 + render_ddl()
└── tests/
    ├── test_cli.py
    ├── test_config.py
    ├── test_schema.py
    └── test_license_check.py
```

---

### 任务 1：工程初始化（pyproject + LICENSE + 包骨架）

**文件：**
- 创建：`pyproject.toml`、`LICENSE`、`src/codesentry/__init__.py`、`src/codesentry/db/__init__.py`
- 不创建测试（纯配置任务，验证靠 uv sync 本身）

- [ ] **步骤 1：创建 `pyproject.toml`**

```toml
[project]
name = "codesentry"
version = "0.1.0"
description = "LLM multi-agent code security audit platform"
requires-python = ">=3.11"
license = "Apache-2.0"
dependencies = [
    "typer>=0.12",
    "rich>=13",
    "pydantic-settings>=2.2",
]

[project.scripts]
codesentry = "codesentry.cli:app"

[dependency-groups]
dev = [
    "pytest>=8",
    "ruff>=0.5",
    "mypy>=1.10",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

M0 依赖刻意最小（langgraph/psycopg/tree-sitter 等 M1 起按需添加）；mypy 配置暂 minimal，M1 收紧。

- [ ] **步骤 2：创建 `LICENSE`**（Apache-2.0 标准全文，含版权行 `Copyright 2026 CodeSentry contributors`）

- [ ] **步骤 3：创建包骨架**——`src/codesentry/__init__.py` 内容：`__version__ = "0.1.0"`；`src/codesentry/db/__init__.py` 空文件

- [ ] **步骤 4：验证**

运行：`uv sync && uv run python -c "import codesentry; print(codesentry.__version__)"`
预期：成功打印 `0.1.0`

- [ ] **步骤 5：Commit**

```bash
git add pyproject.toml LICENSE uv.lock src/codesentry/__init__.py src/codesentry/db/__init__.py
git commit -m "feat(m0): project skeleton with pyproject, LICENSE (Apache-2.0), package layout"
```

### 任务 2：配置系统（TDD）

**文件：**
- 创建：`src/codesentry/config.py`
- 测试：`tests/test_config.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_config.py
import os

import pytest

from codesentry.config import Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """隔离环境变量与 .env，测纯默认值。"""
    monkeypatch.setattr(Settings, "settings_customise_sources", ...)
```

> 实现注意：pydantic-settings 测试隔离优先用 `_env_file=None` 构造 + monkeypatch 删 `CODESENTRY_*` 环境变量，不折腾 override 源。测试写法：

```python
def _fresh(monkeypatch):
    for k in list(os.environ):
        if k.startswith("CODESENTRY_"):
            monkeypatch.delenv(k)
    return Settings(_env_file=None)


def test_budget_defaults(monkeypatch):
    s = _fresh(monkeypatch)
    assert s.max_tokens == 500_000
    assert s.max_tool_calls == 500
    assert s.max_cost_usd == 10.0
    assert s.max_findings == 200


def test_switch_defaults(monkeypatch):
    s = _fresh(monkeypatch)
    assert s.human_review is False
    assert s.temperature == 0.0
    assert s.poc_run == "off"
    assert s.web_bind == "0.0.0.0"
    assert s.work_dir == ".codesentry"
    assert s.allow_oss_codeql is False


def test_env_override(monkeypatch):
    monkeypatch.setenv("CODESENTRY_MAX_TOKENS", "1000")
    s = Settings(_env_file=None)
    assert s.max_tokens == 1000


def test_engines_bin_paths(monkeypatch):
    s = _fresh(monkeypatch)
    assert s.codeql_bin == "codeql"
    assert s.joern_bin == "joern"
    assert s.semgrep_bin == "semgrep"
```

`allow_oss_codeql` 断言仅字段存在 + 默认 False；Gate 强制逻辑属 M1（agent.md FR-3），M0 不实现。

- [ ] **步骤 2：运行测试验证失败**

运行：`uv run pytest tests/test_config.py -v`
预期：FAIL（`ModuleNotFoundError: codesentry.config`）

- [ ] **步骤 3：实现 `src/codesentry/config.py`**

```python
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CODESENTRY_", env_file=".env", extra="ignore")

    # paths
    work_dir: str = ".codesentry"
    pgdata_host: str = ""

    # budget (D14)
    max_tokens: int = 500_000
    max_tool_calls: int = 500
    max_cost_usd: float = 10.0
    max_findings: int = 200

    # llm (D5, D14)
    model_base_url: str = ""
    model_api_key: str = ""  # 永不写入日志/报告
    fast_model: str = ""
    deep_model: str = ""
    temperature: float = 0.0

    # embedding (D10)
    embedding_model: str = ""

    # poc (D28, D32)
    poc_run: Literal["off", "sandbox", "target"] = "off"

    # web (D36)
    web_bind: str = "0.0.0.0"

    # human review (FR-9)
    human_review: bool = False

    # engines (FR-3 探测)
    codeql_bin: str = "codeql"
    joern_bin: str = "joern"
    semgrep_bin: str = "semgrep"

    # gate 开关位（强制逻辑 M1 在 ScanAgent）
    allow_oss_codeql: bool = False


def get_settings() -> Settings:
    return Settings()
```

- [ ] **步骤 4：运行测试验证通过**

运行：`uv run pytest tests/test_config.py -v`
预期：4 个测试全 PASS

- [ ] **步骤 5：Commit**

```bash
git add src/codesentry/config.py tests/test_config.py
git commit -m "feat(m0): config system with spec defaults (D14/D28/D36)"
```

### 任务 3：DB schema 常量与 DDL 骨架（TDD）

**文件：**
- 创建：`src/codesentry/db/schema.py`
- 测试：`tests/test_schema.py`

**范围声明：** M0 只建 schema 框架（2 schema + pgvector extension），不建任何表；`scans`/`findings` 等表 DDL 随所属里程碑增量落。schema 测试不连接真实数据库（连库集成测试 M2 起用 testcontainers，agent.md §10）。

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_schema.py
from codesentry.db.schema import BUSINESS_SCHEMA, CHECKPOINT_SCHEMA, render_ddl


def test_schema_names():
    assert BUSINESS_SCHEMA == "codesentry"
    assert CHECKPOINT_SCHEMA == "langgraph"
    assert BUSINESS_SCHEMA != CHECKPOINT_SCHEMA


def test_render_ddl_contains_schemas_and_extension():
    ddl = render_ddl()
    assert "CREATE SCHEMA IF NOT EXISTS codesentry;" in ddl
    assert "CREATE SCHEMA IF NOT EXISTS langgraph;" in ddl
    assert "CREATE EXTENSION IF NOT EXISTS vector;" in ddl
```

- [ ] **步骤 2：运行测试验证失败**

运行：`uv run pytest tests/test_schema.py -v`
预期：FAIL（模块不存在）

- [ ] **步骤 3：实现 `src/codesentry/db/schema.py`**

```python
BUSINESS_SCHEMA = "codesentry"
CHECKPOINT_SCHEMA = "langgraph"


def render_ddl() -> str:
    """M0 DDL 骨架：业务/checkpoint 双 schema + pgvector 扩展。表 DDL 由 M1+ 增量追加。"""
    return "\n".join(
        [
            f"CREATE SCHEMA IF NOT EXISTS {BUSINESS_SCHEMA};",
            f"CREATE SCHEMA IF NOT EXISTS {CHECKPOINT_SCHEMA};",
            "CREATE EXTENSION IF NOT EXISTS vector;",
        ]
    )
```

（返回值末尾可加换行，实现者裁量；测试断言按上/satisfy上面三行。）

- [ ] **步骤 4：运行测试验证通过**

运行：`uv run pytest tests/test_schema.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add src/codesentry/db/schema.py tests/test_schema.py
git commit -m "feat(m0): db schema constants and DDL skeleton (two schemas + pgvector)"
```

### 任务 4：CLI 八命令骨架（TDD）

**文件：**
- 创建：`src/codesentry/cli.py`、`src/codesentry/cli_commands.py`
- 测试：`tests/test_cli.py`（任务 1 期间此文件不存在，本任务创建）

**命令清单（八命令，agent.md D13+D25）：** `init-db`、`scan`、`diff`、`report`、`kb`、`engines`、`agents`、`skills`。

**占位策略：** `scan/diff/report/kb/agents/skills` 六个命令 M0 为占位（输出 `[M1] 未实现 — 见 agent.md §9`，exit 1）；`init-db` 与 `engines` 两个命令 M0 即真实现（init-db 连库执行 DDL 推到任务 5 完成，本任务只注册；engines 纯本地探测，直接真实现）。

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_cli.py
import pytest
from typer.testing import CliRunner

import codesentry.cli as cli_mod

runner = CliRunner()

ALL_COMMANDS = ["init-db", "scan", "diff", "report", "kb", "engines", "agents", "skills"]
PLACEHOLDER_COMMANDS = ["scan", "diff", "report", "kb", "agents", "skills"]


@pytest.mark.parametrize("cmd", ALL_COMMANDS)
def test_subcommand_registered(cmd):
    result = runner.invoke(cli_mod.app, [cmd, "--help"])
    assert result.exit_code == 0, f"命令 {cmd} 未注册"


@pytest.mark.parametrize("cmd", PLACEHOLDER_COMMANDS)
def test_placeholder_exits_1_with_hint(cmd):
    result = runner.invoke(cli_mod.app, [cmd])
    assert result.exit_code == 1, f"{cmd} 未实现却 exit {result.exit_code}"
    assert "未实现" in result.output
    assert "agent.md" in result.output


def test_engines_check_reports_probe(monkeypatch):
    # 探测是真实的：monkeypatch shutil.which 让三个引擎都"存在"
    monkeypatch.setattr("codesentry.cli_commands.shutil.which", lambda name: f"/fake/path/{name}")
    result = runner.invoke(cli_mod.app, ["engines"])
    assert result.exit_code == 0
    for name in ("codeql", "joern", "semgrep", "java"):
        assert name in result.output


def test_engines_check_missing_exits_1(monkeypatch):
    monkeypatch.setattr("codesentry.cli_commands.shutil.which", lambda name: None)
    # java 也探测不到
    result = runner.invoke(cli_mod.app, ["engines"])
    assert result.exit_code == 1
```

- [ ] **步骤 2：运行测试验证失败**

运行：`uv run pytest tests/test_cli.py -v`
预期：FAIL（`codesentry.cli` 不存在）

- [ ] **步骤 3：实现 `cli.py` 与 `cli_commands.py`**

`src/codesentry/cli.py`：

```python
import typer

from codesentry import cli_commands

app = typer.Typer(no_args_is_help=True, help="CodeSentry — LLM multi-agent code audit platform")

app.command(name="init-db")(cli_commands.init_db)
app.command(name="scan")(cli_commands.scan_cmd)
app.command(name="diff")(cli_commands.diff_cmd)
app.command(name="report")(cli_commands.report_cmd)
app.command(name="kb")(cli_commands.kb_cmd)
app.command(name="engines")(cli_commands.engines_check)
app.command(name="agents")(cli_commands.agents_list)
app.command(name="skills")(cli_commands.skills_cmd)
```

`src/codesentry/cli_commands.py` 要点（实现者按测试写函数）：

```python
import shutil
import sys

import typer

_MILESTONE_HINT = {"scan": "M1", "diff": "M3", "report": "M1", "kb": "M2", "agents": "M3", "skills": "M3"}


def _not_implemented(cmd: str) -> int:
    typer.echo(f"[{_MILESTONE_HINT[cmd]}] {cmd} 未实现 — 见 agent.md §9 里程碑计划", err=True)
    return 1
```

各占位命令函数体即 `raise typer.Exit(_not_implemented("scan"))` 形态。`engines_check` 真实现：`shutil.which` 探测 config 中三个 engine bin + `java`，rich table 输出「引擎 / 路径 / 状态」，三个引擎全缺失 → exit 1（java 缺失仅警告不计入 exit 逻辑——Joern 在大部分安装里有自带 JRE 路径，细则 M1 定）。

`scan` 占位但**声明 `--oss` 旗标与 `--skills` 选项**（参数签名先占位固定，M1 接逻辑；typer 里 flag 定义了未用不报错）。

- [ ] **步骤 4：运行测试验证通过**

运行：`uv run pytest tests/test_cli.py -v`
预期：全部 PASS

- [ ] **步骤 5：手动冒烟**

运行：`uv run codesentry --help && uv run codesentry engines`
预期：帮助信息列出八命令；engines 探测表按本机真实情况输出

- [ ] **步骤 6：Commit**

```bash
git add src/codesentry/cli.py src/codesentry/cli_commands.py tests/test_cli.py
git commit -m "feat(m0): CLI skeleton with 8 commands; engines check real probe; placeholders exit 1"
```

### 任务 5：docker-compose + `.env.example` 重写 + init-db 接真

**文件：**
- 创建：`docker-compose.yml`
- 重写：`.env.example`（替换旧 CodeQL 专有配置段）
- 修改：`src/codesentry/cli_commands.py`（init-db 从占位变真实现）
- 测试：`tests/test_schema.py` 增加一条（init-db 干跑复用 render_ddl；连库验证在 M2）

- [ ] **步骤 1：扩展失败的测试**

```python
# tests/test_schema.py 追加
from codesentry.config import Settings


def test_init_db_dry_run(monkeypatch, capsys):
    """init-db 在 --dry-run 下打印 DDL 不连库。"""
    from codesentry.cli_commands import init_db

    # init_db(dry_run=True) 分支：调用 render_ddl 并 echo，不创建 psycopg 连接
    init_db(dry_run=True)
    out = capsys.readouterr().out
    assert "CREATE SCHEMA IF NOT EXISTS codesentry" in out
    assert "vector" in out
```

> `init_db` 签名：`def init_db(dry_run: bool = False) -> None`。真实模式：用 `config.get_settings().database_url` 建 psycopg 连接，跑 `render_ddl()`，成功后 echo schema 清单。M0 里 psycopg 尚未加依赖——**此任务一并添加 `psycopg[binary]` 到 pyproject dependencies**（M0 需要，不属于越界）。无库时 init-db 真模式应报错退出 1 并提示先 `docker compose up -d`。

- [ ] **步骤 2：运行验证失败** → `uv run pytest tests/test_schema.py -v` 预期 FAIL（init_db 无 dry_run 参数/不打印）

- [ ] **步骤 3：实现 init-db 真实现 + 添加 psycopg 依赖**

- pyproject `dependencies` 追加 `"psycopg[binary]>=3.2"`
- `DATABASE_URL` 进配置：`config.py` 加字段 `database_url: str = "postgresql://codesentry:codesentry@127.0.0.1:5432/codesentry"`
- `cli_commands.init_db(dry_run)`：`dry_run=True` → echo render_ddl() 后 return；否则 psycopg 连 database_url 执行 render_ddl()，异常时 echo 提示 `docker compose up -d` 并 exit 1
- `cli.py` 注册处传递：`app.command(name="init-db")(cli_commands.init_db)` 需要适配 typer 选项——改为 `@app.command()` 装饰器模式或添加 `typer.Option` 包装，实现者取其一并保证 `--dry-run` 存在

- [ ] **步骤 4：运行测试验证通过** → `uv run pytest tests/test_schema.py -v` PASS

- [ ] **步骤 5：写 `docker-compose.yml`**

要求（不得偏离）：

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    container_name: codesentry-db
    environment:
      POSTGRES_USER: codesentry
      POSTGRES_PASSWORD: ${CODESENTRY_PG_PASSWORD:?set CODESENTRY_PG_PASSWORD}
      POSTGRES_DB: codesentry
    volumes:
      - ${CODESENTRY_PGDATA_HOST:?set CODESENTRY_PGDATA_HOST to mount-disk absolute path}:/var/lib/postgresql/data
    ports:
      - "127.0.0.1:5432:5432"
    restart: unless-stopped
```

- 卷源用 `:?` 语法强制非空（审查重点 2）；注释注明必须绝对路径
- PG 端口仅绑主机回环 `127.0.0.1:5432`（PG 数据面不留公网；WebUI 的 0.0.0.0 决策 D36 针对应用端口，不适用于 DB）
- 不放 work 目录卷（work dir 属应用侧）；M5 加 web 服务时再改此文件

- [ ] **步骤 6：重写 `.env.example`**

完整内容（执行者逐行照抄）：

```bash
# CodeSentry configuration template — copy to .env and fill in.
# 每个键映射 src/codesentry/config.py 的同名字段（前缀 CODESENTRY_）。

# ---- PostgreSQL (agent.md §8, D18) ----
# 容器内连接串；密码需与 CODESENTRY_PG_PASSWORD 一致
CODESENTRY_DATABASE_URL=postgresql://codesentry:CHANGE_ME@127.0.0.1:5432/codesentry
CODESENTRY_PG_PASSWORD=CHANGE_ME
# 挂载盘绝对路径（docker compose 数据卷源，必须非空）——如 /mnt/data/codesentry/pgdata
CODESENTRY_PGDATA_HOST=
# 扫描工作目录（Joern CPG 等大文件落此，建议挂载盘）
CODESENTRY_WORK_DIR=.codesentry

# ---- Engines (FR-2/FR-3, D2, D15) ----
# CodeQL 仅用于用户声明开源的目标（Gate 在 ScanAgent 强制，M1）；平台不分发 CodeQL
CODESENTRY_CODEQL_BIN=codeql
CODESENTRY_JOERN_BIN=joern
CODESENTRY_SEMGREP_BIN=semgrep
# 许可 Gate 开关位（配合 --oss；强制逻辑 M1）
CODESENTRY_ALLOW_OSS_CODEQL=false

# ---- Audit budget (D14) ----
CODESENTRY_MAX_TOKENS=500000
CODESENTRY_MAX_TOOL_CALLS=500
CODESENTRY_MAX_COST_USD=10
CODESENTRY_MAX_FINDINGS=200
CODESENTRY_HUMAN_REVIEW=false

# ---- LLM (D5, D14) ----
CODESENTRY_MODEL_BASE_URL=
CODESENTRY_MODEL_API_KEY=
CODESENTRY_FAST_MODEL=
CODESENTRY_DEEP_MODEL=
CODESENTRY_TEMPERATURE=0

# ---- Embedding (D10) ----
CODESENTRY_EMBEDDING_MODEL=

# ---- PoC (D28, D32) ----
# off=只生成不执行；sandbox=平台内置隔离容器；target=用户自备环境
CODESENTRY_POC_RUN=off

# ---- Skill injection limits (D34) ----
CODESENTRY_SKILL_MAX_PER=8192
CODESENTRY_SKILL_MAX_TOTAL=32768

# ---- WebUI (D36) ----
CODESENTRY_WEB_BIND=0.0.0.0
```

- 旧 `.env.example` 里的 `CODESENTRY_LANGUAGE`、`CODESENTRY_DB_BUILD_MODE`、`CODESENTRY_QUERY_PACK`、`CODESENTRY_CODEQL_TIMEOUT`、`CODESENTRY_QUERY_TIMEOUT` 等 CodeQL 通道参数**全部移除**（M1 计划再议是否以新形式回归）
- 新键 `SKILL_MAX_PER`/`SKILL_MAX_TOTAL` 同步加进 `config.py`（`skill_max_per: int = 8192` / `skill_max_total: int = 32768`）并补测试（在 test_config.py 加 2 个断言）

- [ ] **步骤 7：compose 冒烟（如本机 docker 可用）**

运行：`CODESENTRY_PGDATA_HOST=/tmp/codesentry-test-pgdata CODESENTRY_PG_PASSWORD=devtest docker compose up -d && sleep 3 && CODESENTRY_PG_PASSWORD=devtest uv run codesentry init-db`
预期：容器起、init-db 输出双 schema + extension 成功；随后 `docker compose down -v && rm -rf /tmp/codesentry-test-pgdata`
（docker 不可用的环境：跳过并记录，验收以 M2 testcontainers 连库测试补位）

- [ ] **步骤 8：Commit**

```bash
git add docker-compose.yml .env.example pyproject.toml uv.lock src/codesentry/config.py src/codesentry/cli_commands.py tests/test_schema.py tests/test_config.py
git commit -m "feat(m0): docker-compose (pg16+pgvector, mounted volume), .env.example rewrite, init-db real"
```

### 任务 6：license 检查脚本（§3 红线的 CI 工具）

**文件：**
- 创建：`scripts/check_licenses.py`
- 测试：`tests/test_license_check.py`

**M0 检查范围：** ① CodeQL 红线（发行物无 CodeQL 二进制 / `*.ql` 查询文件 / Python 源中的 `import codeql`）；② Semgrep 官方规则红线（无 `semgrep-rules/` 目录）。依赖 license 表推迟到 M1（M0 时依赖少且无风险项，agent.md §3 的"依赖逐项记录 license"由 M1 起逐轮收紧）。

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_license_check.py
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_licenses.py"


def _git_commit_all(repo: Path):
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "x", "--allow-empty"],
        cwd=repo, check=True, capture_output=True,
    )


def _run(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT)], cwd=repo, capture_output=True, text=True)


def test_clean_repo_passes(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "src.py").write_text("print('hi')")
    _git_commit_all(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "passed" in r.stdout


def test_ql_file_violates(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "evil.ql").write_text("select 1")
    _git_commit_all(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "evil.ql" in r.stdout + r.stderr


def test_semgrep_rules_dir_violates(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    rules = tmp_path / "semgrep-rules"
    rules.mkdir()
    (rules / "r.yml").write_text("rules: []")
    _git_commit_all(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 1


def test_import_codeql_txt_violates(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "x.py").write_text("import codeql  # bad")
    _git_commit_all(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 1
```

- [ ] **步骤 2：运行测试验证失败**

运行：`uv run pytest tests/test_license_check.py -v`
预期：FAIL（脚本不存在）

- [ ] **步骤 3：实现 `scripts/check_licenses.py`**

仅标准库（`subprocess`、`fnmatch`、`pathlib`、`sys`）。要点：
- `#!/usr/bin/env python3` shebang，`chmod +x`
- 用 `git ls-files` 取发行物文件清单（在 repo 内用 `subprocess` 执行；不在 git 仓库内时报错 exit 2）
- `check_codeql_absence`：文件名匹配 `*.ql`、`*.qll`、`codeql*`（含路径中出现 codeql 目录名）；文本文件（< 1MB）内容 grep `import codeql` / `from codeql`
- `check_semgrep_rules_absence`：路径含 `semgrep-rules/` 目录条目
- 违规列表打印到 stdout，逐行 `[violation] <path>: <reason>`；全部通过打印 `license check passed`；有违规 exit 1
- 注意排除本脚本自身对 "codeql" 字样的自匹配（脚本内容含检测词——用文件名白名单或只扫非脚本文件；实现者取「跳过自身」即可）

- [ ] **步骤 4：运行测试验证通过**

运行：`uv run pytest tests/test_license_check.py -v`
预期：4 个测试 PASS

- [ ] **步骤 5：对本仓库跑一遍并 commit**

运行：`python3 scripts/check_licenses.py`
预期：`license check passed`（本仓库当前干净）

```bash
git add scripts/check_licenses.py tests/test_license_check.py
git commit -m "feat(m0): license red-line check script (CodeQL absence, semgrep-rules absence)"
```

### 任务 7：收尾——全仓 lint/type/测试 + 里程碑验收

**文件：** 无新文件；可能对前 6 个任务产物做小修

- [ ] **步骤 1：ruff + mypy 清零**

运行：`uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
预期：无报错（mypy M0 mininal 配置，新增类型错误当轮修）

- [ ] **步骤 2：全量测试**

运行：`uv run pytest -q`
预期：全 PASS（约 15+ 用例）

- [ ] **步骤 3：M0 验收核对（agent.md §9）**

逐项确认并在下方勾选：
- [ ] `docker compose` 可起库（任务 5 步骤 7 或显式记录跳过原因）
- [ ] 八命令可运行：占位命令 exit 1 + 提示；init-db/engines 真实现
- [ ] `python3 scripts/check_licenses.py` 可跑且通过
- [ ] `.env.example` 无 CodeQL 通道残留键、无默认密码明文键值（仅占位 `CHANGE_ME`）

- [ ] **步骤 4：Commit（如有小修）并推送（§0 第 8 步）**

```bash
git add -A
git commit -m "chore(m0): lint/type/test cleanup, M0 acceptance"   # 有改动时
git push origin main
```

（push 需远程认证可用；当前环境 HTTPS/SSH 认证均未配置，无法推送时明确报告阻塞点，由需求方运行 `! gh auth login` 或配置 SSH key 后补推。）

---

## 任务依赖与并发（§0 第 4 步）

```
任务1 ──→ 任务2 ──→ 任务4 ──→ 任务5 ──→ 任务7
              └────→ 任务3 ──┘        │
                        任务6（与 2-5 并行，仅依赖任务1）
```

- 任务 1 完成后，任务 2/6 可并行；任务 3 与 2/6 并行
- 任务 4 依赖任务 2（config）；任务 5 依赖任务 3+4；任务 7 收口
- 可并发的三个子 agent：{任务2}、{任务3}、{任务6}；随后 {任务4}；随后 {任务5}；收口 {任务7}

## 里程碑状态表（§0 第 8 步要求：每轮结束回填 agent.md）

| 里程碑 | 状态 | spec | 验收记录 |
|---|---|---|---|
| M0 脚手架 | 本计划执行中 | `doc/2026-10-18-m0-scaffold-plan.md` | 待第 7 步回填 |
| M1–M5 | 未开始 | — | — |
