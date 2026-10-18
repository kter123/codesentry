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

    # web (D36)
    web_bind: str = "0.0.0.0"

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
