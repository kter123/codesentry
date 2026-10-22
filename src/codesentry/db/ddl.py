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

-- M6.1 控制平面：LLM 配置
CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.llm_profiles (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL DEFAULT 'openai-compatible',
    protocol TEXT NOT NULL DEFAULT 'openai-compatible',
    model_prefix_policy TEXT NOT NULL DEFAULT 'strip',
    base_url TEXT NOT NULL,
    api_key_cipher TEXT NOT NULL DEFAULT '',
    fast_model TEXT NOT NULL DEFAULT '',
    deep_model TEXT NOT NULL DEFAULT '',
    temperature REAL NOT NULL DEFAULT 0.0,
    max_tokens INT NOT NULL DEFAULT 0,
    timeout_s INT NOT NULL DEFAULT 60,
    max_concurrency INT NOT NULL DEFAULT 4,
    input_price_per_1k REAL NOT NULL DEFAULT 0,
    output_price_per_1k REAL NOT NULL DEFAULT 0,
    capabilities JSONB NOT NULL DEFAULT '{{}}',
    extra_headers JSONB NOT NULL DEFAULT '{{}}',
    model_catalog JSONB NOT NULL DEFAULT '[]',
    model_protocols JSONB NOT NULL DEFAULT '{{}}',
    quota_windows JSONB NOT NULL DEFAULT '[]',
    billing_mode TEXT NOT NULL DEFAULT 'metered',
    fallback_profile_id BIGINT REFERENCES {BUSINESS_SCHEMA}.llm_profiles(id) ON DELETE SET NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- M6.1 控制平面：LLM 用量明细
CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.llm_usage (
    id BIGSERIAL PRIMARY KEY,
    scan_id BIGINT,
    agent TEXT NOT NULL,
    profile_id BIGINT,
    model TEXT NOT NULL,
    prompt_tokens INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    latency_ms INT NOT NULL DEFAULT 0,
    ok BOOLEAN NOT NULL DEFAULT TRUE,
    error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS llm_usage_created_idx ON {BUSINESS_SCHEMA}.llm_usage (created_at);
CREATE INDEX IF NOT EXISTS llm_usage_scan_idx ON {BUSINESS_SCHEMA}.llm_usage (scan_id);
CREATE INDEX IF NOT EXISTS llm_usage_agent_idx ON {BUSINESS_SCHEMA}.llm_usage (agent);

-- M6.1 控制平面：配置变更审计
CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.config_audit (
    id BIGSERIAL PRIMARY KEY,
    actor TEXT NOT NULL DEFAULT 'system',
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    before JSONB,
    after JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS config_audit_created_idx ON {BUSINESS_SCHEMA}.config_audit (created_at);

-- M6.1 最小认证
CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'viewer',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.api_tokens (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES {BUSINESS_SCHEMA}.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    token_prefix TEXT NOT NULL,
    token_hash CHAR(64) NOT NULL UNIQUE,
    scopes JSONB NOT NULL DEFAULT '["scan:read","scan:write"]',
    expires_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS api_tokens_hash_idx ON {BUSINESS_SCHEMA}.api_tokens (token_hash);

-- M6.1 既有表扩展
CREATE UNIQUE INDEX IF NOT EXISTS llm_profiles_one_default
    ON {BUSINESS_SCHEMA}.llm_profiles (is_default) WHERE is_default;
ALTER TABLE {BUSINESS_SCHEMA}.agent_configs
    ADD COLUMN IF NOT EXISTS llm_profile_id BIGINT REFERENCES {BUSINESS_SCHEMA}.llm_profiles(id) ON DELETE SET NULL;
ALTER TABLE {BUSINESS_SCHEMA}.agent_configs ADD COLUMN IF NOT EXISTS display_name TEXT NOT NULL DEFAULT '';
ALTER TABLE {BUSINESS_SCHEMA}.agent_configs ADD COLUMN IF NOT EXISTS capabilities JSONB NOT NULL DEFAULT '{{}}';
ALTER TABLE {BUSINESS_SCHEMA}.agent_configs ADD COLUMN IF NOT EXISTS timeout_s INT NOT NULL DEFAULT 120;
ALTER TABLE {BUSINESS_SCHEMA}.agent_configs ADD COLUMN IF NOT EXISTS max_iterations INT NOT NULL DEFAULT 8;
ALTER TABLE {BUSINESS_SCHEMA}.agent_configs ADD COLUMN IF NOT EXISTS temperature_override REAL;
ALTER TABLE {BUSINESS_SCHEMA}.agent_configs ADD COLUMN IF NOT EXISTS ab_json JSONB NOT NULL DEFAULT '{{}}';
ALTER TABLE {BUSINESS_SCHEMA}.agent_configs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE {BUSINESS_SCHEMA}.prompt_versions ADD COLUMN IF NOT EXISTS body_sha256 TEXT NOT NULL DEFAULT '';
WITH ranked AS (
    SELECT id, row_number() OVER (PARTITION BY agent ORDER BY version DESC) AS rn
    FROM {BUSINESS_SCHEMA}.prompt_versions WHERE active
)
UPDATE {BUSINESS_SCHEMA}.prompt_versions p SET active = FALSE
FROM ranked r WHERE p.id = r.id AND r.rn > 1;
CREATE UNIQUE INDEX IF NOT EXISTS prompt_versions_one_active
    ON {BUSINESS_SCHEMA}.prompt_versions (agent) WHERE active;

ALTER TABLE {BUSINESS_SCHEMA}.skill_assignments ADD COLUMN IF NOT EXISTS version_pin INT;
ALTER TABLE {BUSINESS_SCHEMA}.skill_assignments ADD COLUMN IF NOT EXISTS priority INT NOT NULL DEFAULT 100;

ALTER TABLE {BUSINESS_SCHEMA}.scans ADD COLUMN IF NOT EXISTS llm_profile_id BIGINT;
ALTER TABLE {BUSINESS_SCHEMA}.scans ADD COLUMN IF NOT EXISTS llm_snapshot JSONB NOT NULL DEFAULT '{{}}';
ALTER TABLE {BUSINESS_SCHEMA}.scans ADD COLUMN IF NOT EXISTS graph_snapshot JSONB NOT NULL DEFAULT '{{}}';
ALTER TABLE {BUSINESS_SCHEMA}.scans ADD COLUMN IF NOT EXISTS deploy_status TEXT NOT NULL DEFAULT '';
ALTER TABLE {BUSINESS_SCHEMA}.scans ADD COLUMN IF NOT EXISTS deploy_log TEXT NOT NULL DEFAULT '';
ALTER TABLE {BUSINESS_SCHEMA}.scans ADD COLUMN IF NOT EXISTS target_url TEXT NOT NULL DEFAULT '';
ALTER TABLE {BUSINESS_SCHEMA}.scans ADD COLUMN IF NOT EXISTS report_dir TEXT NOT NULL DEFAULT '';

ALTER TABLE {BUSINESS_SCHEMA}.findings ADD COLUMN IF NOT EXISTS verification_method TEXT NOT NULL DEFAULT '';
ALTER TABLE {BUSINESS_SCHEMA}.findings ADD COLUMN IF NOT EXISTS verification_nonce TEXT NOT NULL DEFAULT '';
ALTER TABLE {BUSINESS_SCHEMA}.findings ADD COLUMN IF NOT EXISTS confidence_parts JSONB NOT NULL DEFAULT '{{}}';
ALTER TABLE {BUSINESS_SCHEMA}.findings ADD COLUMN IF NOT EXISTS tool_trace JSONB NOT NULL DEFAULT '[]';

-- M6.4 Agent Artifacts 审查链（哈希链）
CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.agent_artifacts (
    id BIGSERIAL PRIMARY KEY,
    scan_id BIGINT NOT NULL REFERENCES {BUSINESS_SCHEMA}.scans(id) ON DELETE CASCADE,
    seq INT NOT NULL,
    node TEXT NOT NULL,
    input_preview TEXT NOT NULL DEFAULT '',
    output_preview TEXT NOT NULL DEFAULT '',
    input_digest CHAR(64) NOT NULL,
    output_digest CHAR(64) NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    tokens INT NOT NULL DEFAULT 0,
    prev_sha256 CHAR(64) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scan_id, seq)
);
CREATE INDEX IF NOT EXISTS agent_artifacts_scan_idx ON {BUSINESS_SCHEMA}.agent_artifacts (scan_id, seq);

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.calibration_params (
    id BIGSERIAL PRIMARY KEY,
    fit_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    a REAL NOT NULL DEFAULT 1.0,
    b REAL NOT NULL DEFAULT 0.0,
    ece REAL NOT NULL DEFAULT 0.0,
    n INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.graph_templates (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    version INT NOT NULL,
    config JSONB NOT NULL,
    active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.prompt_evals (
    id BIGSERIAL PRIMARY KEY,
    agent TEXT NOT NULL,
    version INT,
    dataset TEXT NOT NULL DEFAULT '',
    recall REAL NOT NULL DEFAULT 0,
    precision REAL NOT NULL DEFAULT 0,
    fp_rate REAL NOT NULL DEFAULT 0,
    false_negatives INT NOT NULL DEFAULT 0,
    ece REAL NOT NULL DEFAULT 0,
    n INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.webhooks (
    id BIGSERIAL PRIMARY KEY,
    url TEXT NOT NULL,
    secret TEXT NOT NULL DEFAULT '',
    events JSONB NOT NULL DEFAULT '["*"]',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- M3.5 RAG 五库：历史案例 / 漏洞模式 / 扫描策略
CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.vuln_cases (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    cwe INT NOT NULL DEFAULT 0,
    lang TEXT NOT NULL DEFAULT '',
    pattern TEXT NOT NULL DEFAULT '',
    exploit_chain JSONB NOT NULL DEFAULT '[]',
    poc TEXT NOT NULL DEFAULT '',
    fix TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    embedding vector,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS vuln_cases_fts_idx ON {BUSINESS_SCHEMA}.vuln_cases
    USING GIN (to_tsvector('simple', title || ' ' || pattern));

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.audit_patterns (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    lang TEXT NOT NULL DEFAULT '',
    cwe INT NOT NULL DEFAULT 0,
    pattern TEXT NOT NULL DEFAULT '',
    guidance TEXT NOT NULL DEFAULT '',
    embedding vector,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.scan_strategies (
    id BIGSERIAL PRIMARY KEY,
    project_profile TEXT NOT NULL,
    languages JSONB NOT NULL DEFAULT '[]',
    strategy JSONB NOT NULL DEFAULT '{{}}',
    embedding vector,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- M3.5 GraphRAG：代码调用图（节点/边）
CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.code_graph_nodes (
    id BIGSERIAL PRIMARY KEY,
    project TEXT NOT NULL,
    node_key TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'function',
    name TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    start_line INT NOT NULL DEFAULT 0,
    end_line INT NOT NULL DEFAULT 0,
    UNIQUE (project, node_key)
);
CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.code_graph_edges (
    id BIGSERIAL PRIMARY KEY,
    project TEXT NOT NULL,
    src_key TEXT NOT NULL,
    dst_key TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'calls'
);
CREATE INDEX IF NOT EXISTS code_graph_edges_src_idx ON {BUSINESS_SCHEMA}.code_graph_edges (project, src_key);
CREATE INDEX IF NOT EXISTS code_graph_edges_dst_idx ON {BUSINESS_SCHEMA}.code_graph_edges (project, dst_key);

CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.review_comments (
    id BIGSERIAL PRIMARY KEY,
    scan_id BIGINT NOT NULL REFERENCES {BUSINESS_SCHEMA}.scans(id) ON DELETE CASCADE,
    finding_id BIGINT REFERENCES {BUSINESS_SCHEMA}.findings(id) ON DELETE CASCADE,
    author TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS review_comments_scan_idx ON {BUSINESS_SCHEMA}.review_comments (scan_id);
"""


def render_full_ddl() -> str:
    return _DDL
