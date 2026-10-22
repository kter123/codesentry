from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CODESENTRY_", env_file=".env", extra="ignore")

    # paths
    work_dir: str = ".codesentry"
    pgdata_host: str = ""

    # database
    database_url: str = "postgresql://codesentry:codesentry@127.0.0.1:5432/codesentry"

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
    embedding_base_url: str = ""
    embedding_api_key: str = ""

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

    # web (D36 修订：默认仅回环；绑定外部地址需显式配置认证)
    web_bind: str = "127.0.0.1"
    secret_key: str = ""
    auth_enabled: bool = False

    # human review (FR-9)
    human_review: bool = False

    # engines (FR-3 探测)
    codeql_bin: str = "codeql"
    joern_bin: str = "joern"
    semgrep_bin: str = "semgrep"

    # skill 注入上限 (D34)
    skill_max_per: int = 8192
    skill_max_total: int = 32768

    # gate 开关位（强制逻辑 M1 在 ScanAgent）
    allow_oss_codeql: bool = False


def get_settings() -> Settings:
    return Settings()
