from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CODESENTRY_", env_file=".env", extra="ignore")

    # paths
    work_dir: str = ".codesentry"
    pgdata_host: str = ""

    # database
    database_url: str = "postgresql://codesentry:codesentry@127.0.0.1:5432/codesentry"

    # budget (D14)：深度审计需要足够 token；per-agent 覆写见 agent_config
    max_tokens: int = 1_200_000
    max_tool_calls: int = 1_500
    max_cost_usd: float = 30.0
    max_findings: int = 500
    # 图构建后同步切块索引（关闭则仅建图，检索走已有 chunks）
    index_on_graph_build: bool = True
    # 记录原始 LLM 调用（脱敏/截断）供 LLM 记录页排查
    record_llm_calls: bool = True
    # 路径中心审计
    path_depth: int = 8
    max_paths: int = 2000
    audit_batch: int = 8
    audit_concurrency: int = 4
    audit_max_rounds: int = 10
    audit_max_paths: int = 240
    audit_entry_only_max: int = 48
    audit_path_timeout_s: int = 60
    audit_path_attempts_max: int = 2
    audit_priority: Literal["proven_first", "score"] = "proven_first"
    path_min_score: float = 0.2
    path_lease_s: int = 900
    scheduler_enabled: bool = True
    scheduler_interval_s: int = 30

    # llm (D5, D14)
    model_base_url: str = ""
    model_api_key: str = ""  # 永不写入日志/报告
    llm_enabled: bool = True
    fast_model: str = ""
    deep_model: str = ""
    temperature: float = 0.0

    # embedding (D10)
    embedding_model: str = ""
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_timeout_s: float = 60.0

    # poc (D28, D32)
    poc_run: Literal["off", "sandbox", "target"] = "off"

    # M6.2 sandbox deploy
    deploy_enabled: bool = True
    deploy_network_mode: Literal["host", "internal"] = "host"
    deploy_port: int = 8080
    deploy_keep: bool = False
    deploy_timeout_s: int = 120
    deploy_mem_mb: int = 512
    deploy_cpu: float = 1.0
    deploy_python_image: str = "python:3.12-slim"
    deploy_php_image: str = "php:8.3-cli"
    deploy_javascript_image: str = "node:20-slim"
    # 镜像策略：config 显式 > 本地 > 远程（仅 allow_remote）
    deploy_image_pull: Literal["never", "missing", "always"] = "missing"
    deploy_java_image: str = ""
    deploy_maven_image: str = ""
    deploy_image_allow_remote: bool = False

    # web (D36 修订：默认仅回环；绑定外部地址需显式配置认证)
    web_bind: str = "127.0.0.1"
    secret_key: str = ""
    auth_enabled: bool = False

    # human review (FR-9)
    human_review: bool = False

    # engines (FR-3 探测)
    codeql_bin: str = "codeql"
    codeql_search_path: str = ""
    codeql_suite: str = ""
    codeql_build_mode: Literal["none", "autobuild", "manual"] = "none"
    codeql_build_command: str = ""
    codeql_timeout_s: int = 1800
    codeql_db_cache: bool = True
    joern_bin: str = "joern"
    semgrep_bin: str = "semgrep"

    # skill 注入上限 (D34)
    skill_max_per: int = 8192
    skill_max_total: int = 32768

    # gate 开关位（强制逻辑 M1 在 ScanAgent）
    allow_oss_codeql: bool = False


def get_settings() -> Settings:
    return Settings()
