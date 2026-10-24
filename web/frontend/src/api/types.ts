export interface AuthUser {
  id?: number
  username: string
  role?: string
  display_name?: string
  enabled?: boolean
}

export interface MeResponse {
  username?: string
  role?: string
  auth_enabled?: boolean
  user?: AuthUser
}

export interface ScanRow {
  id: number
  repo_path: string
  OSS?: boolean
  status: string
  mode?: string
  created?: string
  deploy_status?: string
  target_url?: string
  deploy_log?: string
  error_reason?: string
  timeline?: NodeRun[]
}

export interface NodeRun {
  node: string
  started?: string
  ended?: string
  duration_ms?: number
  tokens?: number
  tool_calls?: number
  status?: string
  error?: string
}

export interface GraphFinding {
  id: number
  rule_id?: string
  cwe?: string
  severity?: string
  confidence?: number
  file?: string
  file_rel?: string
  line?: number
  message?: string
  engine?: string
  verdict?: string
  [key: string]: unknown
}

export interface GraphNode {
  id: string
  kind?: string
  file?: string
  name?: string
  start?: number
  end?: number
  findings?: GraphFinding[]
}

export interface GraphEdge {
  source: string
  target: string
  kind?: string
}

export interface GraphResponse {
  scan_id: number
  mode?: string
  languages?: string[]
  nodes?: GraphNode[]
  edges?: GraphEdge[]
}

export interface FindingDetail extends GraphFinding {
  scan_id?: number
  taint_metadata?: unknown
  exploit_chain?: unknown
  poc_path?: string
  execution_log?: string
  verification_method?: string
  verification_nonce?: string
  confidence_parts?: unknown
  tool_trace?: unknown
}

export interface UsageRow {
  key: string
  calls: number
  prompt_tokens: number
  completion_tokens: number
  tokens: number
  cost_usd: number
  avg_latency_ms: number
  ok_calls: number
}

export interface LlmProfile {
  id: number
  name: string
  provider?: string
  protocol?: string
  base_url?: string
  api_key?: string
  fast_model?: string
  deep_model?: string
  temperature?: number
  max_tokens?: number
  timeout_s?: number
  max_concurrency?: number
  input_price_per_1k?: number
  output_price_per_1k?: number
  billing_mode?: string
  enabled?: boolean
  is_default?: boolean
  bound_agents?: string[]
  model_catalog?: string[]
  model_protocols?: Record<string, string>
  quota_windows?: unknown[]
  capabilities?: Record<string, unknown>
  extra_headers?: Record<string, string>
  fallback_profile_id?: number | null
  model_prefix_policy?: string
  priority?: number
  pool_exclude?: boolean
  context_window_k?: number
  rate_per_second?: number
  rate_per_minute?: number
  streaming?: boolean
  [key: string]: unknown
}

export interface AgentConfig {
  name: string
  display_name?: string
  enabled?: boolean
  model_role?: string
  llm_profile_id?: number | null
  capabilities?: {
    engines?: string[]
    network?: boolean
    shell?: boolean
    poc_exec?: boolean
    [key: string]: unknown
  }
  timeout_s?: number
  max_iterations?: number
  temperature_override?: number | null
  budget_override?: Record<string, unknown>
  tools_allow?: string[]
  skills_allow?: string[]
  wrapup_prompt?: string
  [key: string]: unknown
}

export interface PromptSummary {
  name: string
  latest_version?: number
  active_version?: number | null
  body_sha256?: string
  preview?: string
}

export interface PromptVersion {
  version: number
  body: string
  active?: boolean
  body_sha256?: string
  created?: string
  created_at?: string
}

export interface SkillRow {
  name: string
  description?: string
  enabled?: boolean
  versions?: number
  assigned?: Record<string, boolean>
  assignments?: Array<{
    agent: string
    enabled: boolean
    version_pin?: number | null
    priority?: number
  }>
  [key: string]: unknown
}

export interface RuleSummary {
  id: string
  languages?: string[]
  severity?: string
  cwe?: string
  message?: string
}

export interface AuditRow {
  id: number
  actor?: string
  action?: string
  target_type?: string
  target_id?: string
  before?: unknown
  after?: unknown
  created_at?: string
}
