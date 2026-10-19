"""M2 全量表 DDL（agent.md §8；M0 render_ddl 扩展）。"""

from codesentry.db.schema import BUSINESS_SCHEMA, CHECKPOINT_SCHEMA

_DDL = f"""
CREATE SCHEMA IF NOT EXISTS {BUSINESS_SCHEMA};
CREATE SCHEMA IF NOT EXISTS {CHECKPOINT_SCHEMA};
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.scans (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    repo_path TEXT NOT NULL,
    license_oss BOOLEAN NOT NULL,
    license_declared_at TIMESTAMPTZ NOT NULL,
    mode TEXT NOT NULL DEFAULT 'full',
    status TEXT NOT NULL DEFAULT 'running',
    prompt_snapshot JSONB NOT NULL DEFAULT '{{}}',
    skill_snapshot JSONB NOT NULL DEFAULT '{{}}'
);

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.findings (
    id BIGSERIAL PRIMARY KEY,
    scan_id BIGINT NOT NULL REFERENCES {BUSINESS_SCHEMA}.scans(id),
    rule_id TEXT NOT NULL,
    cwe INT NOT NULL,
    severity TEXT NOT NULL,
    confidence REAL NOT NULL,
    file TEXT NOT NULL,
    line INT NOT NULL,
    end_line INT,
    message TEXT NOT NULL,
    engine TEXT NOT NULL,
    taint_metadata JSONB NOT NULL DEFAULT '{{}}',
    exploit_chain JSONB,
    poc_path TEXT,
    verdict TEXT,
    execution_log TEXT
);

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.code_chunks (
    id BIGSERIAL PRIMARY KEY,
    project TEXT NOT NULL,
    path TEXT NOT NULL,
    symbol_name TEXT NOT NULL,
    symbol_kind TEXT NOT NULL,
    start_line INT NOT NULL,
    end_line INT NOT NULL,
    signature TEXT NOT NULL DEFAULT '',
    docstring TEXT NOT NULL DEFAULT '',
    call_refs JSONB NOT NULL DEFAULT '[]',
    content TEXT NOT NULL,
    lang TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    embedding vector
);
CREATE INDEX IF NOT EXISTS code_chunks_sha_idx ON {BUSINESS_SCHEMA}.code_chunks (content_sha256);

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.kb_chunks (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    embedding vector,
    lang TEXT NOT NULL DEFAULT 'zh'
);
CREATE INDEX IF NOT EXISTS kb_chunks_sha_idx ON {BUSINESS_SCHEMA}.kb_chunks (content_sha256);
CREATE INDEX IF NOT EXISTS kb_chunks_fts_idx ON {BUSINESS_SCHEMA}.kb_chunks
    USING GIN (to_tsvector('simple', content));

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.budget_ledger (
    id BIGSERIAL PRIMARY KEY,
    scan_id BIGINT NOT NULL REFERENCES {BUSINESS_SCHEMA}.scans(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    tokens_used INT NOT NULL DEFAULT 0,
    tool_calls INT NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    phase TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.node_runs (
    id BIGSERIAL PRIMARY KEY,
    scan_id BIGINT NOT NULL REFERENCES {BUSINESS_SCHEMA}.scans(id),
    node TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    duration_ms INT,
    tokens INT NOT NULL DEFAULT 0,
    tool_calls INT NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ok',
    error TEXT
);

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.agent_configs (
    name TEXT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    model_role TEXT NOT NULL DEFAULT 'fast',
    budget_override JSONB NOT NULL DEFAULT '{{}}'
);

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.prompt_versions (
    id BIGSERIAL PRIMARY KEY,
    agent TEXT NOT NULL,
    version INT NOT NULL,
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    active BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (agent, version)
);

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.skills (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.skill_versions (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL REFERENCES {BUSINESS_SCHEMA}.skills(name),
    version INT NOT NULL,
    body TEXT NOT NULL,
    body_sha256 TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.skill_assignments (
    skill_name TEXT NOT NULL REFERENCES {BUSINESS_SCHEMA}.skills(name),
    agent TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (skill_name, agent)
);

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.rule_sets (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    version INTEGER NOT NULL,
    body TEXT NOT NULL,
    body_sha256 TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE {BUSINESS_SCHEMA}.scans ADD COLUMN IF NOT EXISTS rule_set_version TEXT NOT NULL DEFAULT '';
ALTER TABLE {BUSINESS_SCHEMA}.scans ADD COLUMN IF NOT EXISTS error_reason TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def render_full_ddl() -> str:
    return _DDL
