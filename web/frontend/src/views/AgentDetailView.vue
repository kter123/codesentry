<template>
  <div>
    <page-header
      :title="`Agent · ${form?.display_name || agentName}`"
      :subtitle="`节点 ${agentName} 的 LLM 绑定、Prompt、Skills 与运行统计`"
    >
      <template #actions>
        <el-button @click="$router.push('/agents')">
          <el-icon><Back /></el-icon>
          <span>返回</span>
        </el-button>
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
        <el-button type="primary" :loading="saving" :disabled="!form" @click="save">
          保存配置
        </el-button>
      </template>
    </page-header>

    <error-alert :message="loadError" @retry="load" />
    <error-alert :message="saveError" :retryable="false" />

    <el-row :gutter="18">
      <el-col :xs="24" :lg="15">
        <div v-loading="loading" class="panel">
          <h2 class="panel-title">运行配置</h2>
          <el-form v-if="form" label-position="top">
            <el-row :gutter="14">
              <el-col :xs="24" :sm="12">
                <el-form-item label="显示名称">
                  <el-input v-model="form.display_name" placeholder="Agent 显示名称" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="启用">
                  <el-switch v-model="form.enabled" />
                  <span class="muted" style="margin-left: 10px">停用后该节点在扫描中标记 skipped</span>
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="模型角色">
                  <el-select v-model="form.model_role" style="width: 100%">
                    <el-option label="fast（快速模型）" value="fast" />
                    <el-option label="deep（深度模型）" value="deep" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="LLM Profile 绑定">
                  <el-select
                    v-model="form.llm_profile_id"
                    clearable
                    placeholder="使用全局默认"
                    style="width: 100%"
                  >
                    <el-option
                      v-for="profile in profiles"
                      :key="profile.id"
                      :label="`${profile.name}${profile.is_default ? '（默认）' : ''}`"
                      :value="profile.id"
                    />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="8">
                <el-form-item label="超时 (s)">
                  <el-input-number v-model="form.timeout_s" :min="1" :max="3600" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="8">
                <el-form-item label="最大迭代">
                  <el-input-number v-model="form.max_iterations" :min="1" :max="64" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="8">
                <el-form-item label="温度覆盖（可选）">
                  <el-input-number
                    v-model="temperature"
                    :min="0"
                    :max="2"
                    :step="0.1"
                    :precision="2"
                    style="width: 100%"
                  />
                </el-form-item>
              </el-col>
            </el-row>

            <el-form-item label="能力矩阵">
              <div class="capability-grid">
                <el-checkbox v-model="form.capabilities.network">network</el-checkbox>
                <el-checkbox v-model="form.capabilities.shell">shell</el-checkbox>
                <el-checkbox v-model="form.capabilities.poc_exec">poc_exec</el-checkbox>
              </div>
            </el-form-item>
            <el-form-item label="允许的引擎（逗号分隔）">
              <el-input v-model="enginesText" placeholder="semgrep, codeql, joern" />
            </el-form-item>
            <el-form-item label="工具白名单">
              <el-select
                v-model="form.tools_allow"
                multiple
                filterable
                allow-create
                default-first-option
                placeholder="留空 = 按角色默认（全部可用工具）"
                style="width: 100%"
              >
                <el-option v-for="tool in toolOptions" :key="tool" :label="tool" :value="tool" />
              </el-select>
              <div class="muted" style="font-size: 12px">
                留空表示按角色默认；选择后仅这些工具可被该 Agent 调用。
              </div>
            </el-form-item>
            <el-form-item label="技能白名单">
              <el-select
                v-model="form.skills_allow"
                multiple
                filterable
                clearable
                placeholder="留空 = 使用全部已分配技能"
                style="width: 100%"
              >
                <el-option
                  v-for="skill in allSkills"
                  :key="skill.name"
                  :label="skill.name"
                  :value="skill.name"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="收尾 Prompt（可选）">
              <el-input
                v-model="form.wrapup_prompt"
                class="code-input"
                type="textarea"
                :rows="3"
                placeholder="超时/收尾时追加的指令，例如：先写回已确认 fact 再结束。"
              />
            </el-form-item>
            <el-form-item label="Prompt A/B（JSON）">
              <el-input
                v-model="abText"
                class="code-input"
                type="textarea"
                :rows="3"
                placeholder='{"enabled": true, "a": 1, "b": 2, "ratio": 0.5}'
              />
              <div class="muted" style="font-size: 12px">
                开启后按 scan_id 稳定分流；每次扫描快照记录 ab_arm。
              </div>
            </el-form-item>
            <el-form-item label="预算覆盖（JSON）">
              <el-input
                v-model="budgetText"
                class="code-input"
                type="textarea"
                :rows="4"
                placeholder='{"max_usd": 5, "max_tokens": 200000}'
              />
            </el-form-item>
          </el-form>
          <el-empty v-else-if="!loading" description="无法加载 Agent 配置" />
        </div>
      </el-col>

      <el-col :xs="24" :lg="9">
        <div class="panel">
          <h2 class="panel-title">
            运行统计
            <span class="panel-subtitle">最近 {{ stats?.days ?? 30 }} 天</span>
          </h2>
          <el-descriptions v-if="stats" :column="2" border size="small">
            <el-descriptions-item label="调用次数">{{ stats.calls ?? 0 }}</el-descriptions-item>
            <el-descriptions-item label="成功">{{ stats.ok_calls ?? 0 }}</el-descriptions-item>
            <el-descriptions-item label="成功率">
              {{ ((stats.success_rate ?? 0) * 100).toFixed(1) }}%
            </el-descriptions-item>
            <el-descriptions-item label="Tokens">{{ stats.tokens ?? 0 }}</el-descriptions-item>
            <el-descriptions-item label="P50">{{ stats.p50_ms ?? 0 }} ms</el-descriptions-item>
            <el-descriptions-item label="P95">{{ stats.p95_ms ?? 0 }} ms</el-descriptions-item>
          </el-descriptions>
          <el-empty v-else :image-size="56" description="暂无统计数据" />
        </div>

        <div class="panel">
          <h2 class="panel-title">
            当前 Prompt
            <el-tag v-if="promptInfo" size="small" effect="plain">
              {{ promptInfo.version ? `v${promptInfo.version}` : 'seed' }}
            </el-tag>
          </h2>
          <el-alert
            v-if="promptInfo?.fallback"
            type="info"
            :closable="false"
            show-icon
            title="未激活自定义 Prompt，当前使用代码内置种子 Prompt"
            style="margin-bottom: 10px"
          />
          <el-input
            v-model="promptDraft"
            class="code-input prompt-editor"
            type="textarea"
            :rows="13"
            spellcheck="false"
            placeholder="该 Agent 的生效 Prompt 正文"
          />
          <div class="toolbar" style="margin-top: 10px">
            <el-button size="small" type="primary" :loading="promptSaving" @click="savePrompt">
              保存为新版本
            </el-button>
            <el-button size="small" :loading="previewing" @click="previewPrompt">预览注入</el-button>
            <el-button size="small" :loading="dryRunning" @click="dryRun">Dry-run</el-button>
            <el-button size="small" text type="primary" @click="$router.push(`/prompts?name=${agentName}`)">
              版本 / Diff / 回滚
            </el-button>
          </div>
          <div class="muted" style="font-size: 12px; margin-top: 6px">
            Prompt 与当前 Agent 绑定；保存后立即创建并激活新版本，代码内安全/输出契约尾仍会强制追加。
          </div>
          <el-alert
            v-for="(warning, index) in detailWarnings"
            :key="index"
            type="warning"
            :title="warning"
            :closable="false"
            show-icon
            style="margin-top: 8px"
          />
        </div>

        <div class="panel">
          <h2 class="panel-title">已分配 Skills</h2>
          <el-table v-if="skills.length" :data="skills" size="small">
            <el-table-column prop="name" label="名称" min-width="120" show-overflow-tooltip />
            <el-table-column label="版本" width="80">
              <template #default="{ row }">{{ row.version ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="优先级" width="80">
              <template #default="{ row }">{{ row.priority ?? '—' }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-else :image-size="56" description="未分配 Skills" />
          <div style="margin-top: 10px">
            <el-link type="primary" :underline="false" @click="$router.push('/skills')">
              前往 Skills 分配 →
            </el-link>
          </div>
        </div>
      </el-col>
    </el-row>

    <div class="panel">
      <div class="toolbar">
        <h2 class="panel-title" style="margin: 0">自定义 Agent Preset</h2>
        <div class="grow" />
        <el-select v-model="presetId" clearable placeholder="选择 preset" style="width: 240px">
          <el-option v-for="p in presets" :key="p.id" :label="`${p.name} (v${p.version})`" :value="p.id" />
        </el-select>
        <el-button size="small" type="primary" @click="bindPreset">绑定</el-button>
        <el-button size="small" @click="unbindPreset">解绑</el-button>
        <el-button size="small" @click="openPresetDialog">新建</el-button>
      </div>
      <div class="muted" style="font-size: 12px">
        Preset 覆盖 Prompt/工具/技能/能力，但仍保留代码内安全与输出契约尾。
      </div>
      <div class="toolbar" style="margin-top: 12px; margin-bottom: 0">
        <el-select v-model="compareA" clearable placeholder="版本 A" style="width: 150px">
          <el-option v-for="v in promptVersions" :key="v.version" :label="`v${v.version}`" :value="v.version" />
        </el-select>
        <el-select v-model="compareB" clearable placeholder="版本 B" style="width: 150px">
          <el-option v-for="v in promptVersions" :key="v.version" :label="`v${v.version}`" :value="v.version" />
        </el-select>
        <el-checkbox v-model="compareUseLlm">调用 LLM</el-checkbox>
        <el-button size="small" :loading="comparing" @click="runCompare">试跑对比</el-button>
      </div>
    </div>

    <el-dialog v-model="presetDialog" title="新建 Agent Preset" width="720px">
      <el-form label-position="top">
        <el-row :gutter="12">
          <el-col :xs="24" :sm="12">
            <el-form-item label="名称"><el-input v-model="presetForm.name" /></el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="说明"><el-input v-model="presetForm.description" /></el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="System Prompt">
          <el-input v-model="presetForm.system_prompt" type="textarea" :rows="8" />
        </el-form-item>
        <el-form-item label="工具白名单（逗号分隔）">
          <el-input v-model="presetForm.tools" placeholder="graph_paths, read_source" />
        </el-form-item>
        <el-form-item label="技能白名单（逗号分隔）">
          <el-input v-model="presetForm.skills" placeholder="taint, auth-review" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="presetDialog = false">取消</el-button>
        <el-button type="primary" :loading="presetSaving" @click="createPreset">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="compareVisible" title="Agent 试跑对比" width="820px">
      <template v-if="compareResult">
        <el-alert
          type="info" :closable="false" show-icon
          :title="`A=${compareResult.a.label} (${compareResult.a.token_est} tokens) · B=${compareResult.b.label} (${compareResult.b.token_est} tokens) · LLM=${compareResult.used_llm}`"
          style="margin-bottom: 10px"
        />
        <h3 class="panel-title">Diff</h3>
        <pre class="pre-block">{{ compareResult.diff || '（无差异）' }}</pre>
        <template v-if="compareResult.a.output || compareResult.b.output">
          <h3 class="panel-title" style="margin-top: 12px">A 输出</h3>
          <pre class="pre-block light">{{ compareResult.a.output || compareResult.a.error || '—' }}</pre>
          <h3 class="panel-title" style="margin-top: 12px">B 输出</h3>
          <pre class="pre-block light">{{ compareResult.b.output || compareResult.b.error || '—' }}</pre>
        </template>
      </template>
    </el-dialog>

    <el-dialog v-model="dryRunVisible" title="Agent Dry-run" width="720px">
      <template v-if="dryRunResult">
        <el-descriptions :column="2" border size="small" style="margin-bottom: 12px">
          <el-descriptions-item label="enabled">{{ dryRunResult.enabled }}</el-descriptions-item>
          <el-descriptions-item label="prompt_version">
            {{ dryRunResult.prompt_version ?? 'seed' }}
          </el-descriptions-item>
          <el-descriptions-item label="token_est">{{ dryRunResult.token_est }}</el-descriptions-item>
          <el-descriptions-item label="技能数">
            {{ (dryRunResult.skills as unknown[] | undefined)?.length ?? 0 }}
          </el-descriptions-item>
        </el-descriptions>
        <el-alert
          v-for="(warning, index) in (dryRunResult.warnings as string[] | undefined) || []"
          :key="index"
          type="warning"
          :title="warning"
          :closable="false"
          show-icon
          style="margin-bottom: 8px"
        />
        <pre class="pre-block">{{ dryRunResult.system_prompt || '—' }}</pre>
      </template>
    </el-dialog>

    <el-dialog v-model="previewVisible" title="Prompt 注入预览" width="720px">
      <template v-if="previewResult">
        <el-descriptions :column="2" border size="small" style="margin-bottom: 12px">
          <el-descriptions-item label="prompt_version">
            {{ previewResult.prompt_version ?? 'seed' }}
          </el-descriptions-item>
          <el-descriptions-item label="prompt tokens">
            {{ previewResult.prompt_tokens_est ?? '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="skills tokens">
            {{ previewResult.skills_tokens_est ?? '—' }}
          </el-descriptions-item>
        </el-descriptions>
        <h3 class="panel-title">Prompt 预览</h3>
        <pre class="pre-block light">{{ previewResult.prompt_preview || '—' }}</pre>
        <h3 class="panel-title" style="margin-top: 14px">Skills 注入块</h3>
        <pre class="pre-block">{{ previewResult.skills_block || '（无）' }}</pre>
        <el-alert
          v-for="(warning, index) in (previewResult.warnings as string[] | undefined) || []"
          :key="index"
          type="warning"
          :title="warning"
          :closable="false"
          show-icon
          style="margin-top: 8px"
        />
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Back, Refresh } from '@element-plus/icons-vue'

import { api, errorMessage } from '@/api/client'
import type { AgentConfig, LlmProfile } from '@/api/types'
import ErrorAlert from '@/components/ErrorAlert.vue'
import PageHeader from '@/components/PageHeader.vue'

interface PromptInfo {
  version?: number | null
  body?: string
  fallback?: boolean
}

interface AgentDetailResponse {
  config: AgentConfig
  prompt?: PromptInfo
  skills_block?: string
  warnings?: string[]
}

interface SkillItem {
  name: string
  version?: number | null
  sha256?: string
  priority?: number
}

interface AgentCapabilities {
  engines?: string[]
  network?: boolean
  shell?: boolean
  poc_exec?: boolean
  [key: string]: unknown
}

interface AgentForm extends Omit<AgentConfig, 'capabilities' | 'budget_override'> {
  capabilities: AgentCapabilities
  budget_override: Record<string, unknown>
}

interface AgentStats {
  agent?: string
  days?: number
  calls?: number
  ok_calls?: number
  success_rate?: number
  p50_ms?: number
  p95_ms?: number
  tokens?: number
}

interface AgentPreset {
  id: number
  name: string
  base_agent: string
  description?: string
  system_prompt?: string
  tools_allow?: string[]
  skills_allow?: string[]
  capabilities?: Record<string, unknown>
  enabled?: boolean
  version: number
}

interface PromptVersionRow {
  version: number
  active?: boolean
  body?: string
}

interface CompareResult {
  a: { label: string; token_est: number; output?: string; error?: string; body?: string }
  b: { label: string; token_est: number; output?: string; error?: string; body?: string }
  diff: string
  used_llm: boolean
}

const route = useRoute()
const agentName = computed(() => String(route.params.name || ''))

const loading = ref(false)
const saving = ref(false)
const loadError = ref('')
const saveError = ref('')

const form = ref<AgentForm | null>(null)
const enginesText = ref('')
const budgetText = ref('{}')
const abText = ref('{}')
const temperature = ref<number | null>(null)

const promptInfo = ref<PromptInfo | null>(null)
const promptDraft = ref('')
const promptSaving = ref(false)
const detailWarnings = ref<string[]>([])
const skills = ref<SkillItem[]>([])
const allSkills = ref<Array<{ name: string; description?: string }>>([])
const stats = ref<AgentStats | null>(null)
const profiles = ref<LlmProfile[]>([])

const toolOptions = [
  'read_source', 'search_code', 'read_evidence',
  'graph_search', 'graph_node', 'graph_neighbors', 'graph_paths', 'graph_entrypoints',
]

const dryRunVisible = ref(false)
const dryRunResult = ref<Record<string, unknown> | null>(null)
const dryRunning = ref(false)
const previewVisible = ref(false)
const previewResult = ref<Record<string, unknown> | null>(null)
const previewing = ref(false)

const presets = ref<AgentPreset[]>([])
const presetId = ref<number | null>(null)
const presetDialog = ref(false)
const presetSaving = ref(false)
const presetForm = reactive({
  name: '', description: '', system_prompt: '', tools: '', skills: '',
})
const promptVersions = ref<PromptVersionRow[]>([])
const compareA = ref<number | null>(null)
const compareB = ref<number | null>(null)
const compareUseLlm = ref(false)
const compareVisible = ref(false)
const comparing = ref(false)
const compareResult = ref<CompareResult | null>(null)

function applyConfig(config: AgentConfig): void {
  form.value = {
    ...config,
    capabilities: { ...(config.capabilities || {}) },
    budget_override: { ...(config.budget_override || {}) },
    tools_allow: [...(config.tools_allow || [])],
    skills_allow: [...(config.skills_allow || [])],
    wrapup_prompt: config.wrapup_prompt || '',
  } as AgentForm
  enginesText.value = (config.capabilities?.engines || []).join(', ')
  temperature.value =
    typeof config.temperature_override === 'number' ? config.temperature_override : null
  try {
    budgetText.value = JSON.stringify(config.budget_override || {}, null, 2)
  } catch {
    budgetText.value = '{}'
  }
  try {
    abText.value = JSON.stringify((config as unknown as { ab_json?: unknown }).ab_json || {}, null, 2)
  } catch {
    abText.value = '{}'
  }
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  saveError.value = ''
  const name = agentName.value
  const [detailRes, promptRes, skillsRes, statsRes, profilesRes, allSkillsRes,
    presetsRes, versionsRes] = await Promise.allSettled([
    api.get<AgentDetailResponse>(`/api/agents/${name}`),
    api.get<PromptInfo & { agent?: string }>(`/api/agents/${name}/prompt`),
    api.get<{ skills?: SkillItem[] }>(`/api/agents/${name}/skills`),
    api.get<AgentStats>(`/api/agents/${name}/stats`),
    api.get<{ profiles?: LlmProfile[] }>('/api/llm-profiles'),
    api.get<{ skills?: Array<{ name: string; description?: string }> }>('/api/skills'),
    api.get<{ presets?: AgentPreset[] }>('/api/agent-presets', { base_agent: name }),
    api.get<{ versions?: PromptVersionRow[] }>(`/api/prompts/${name}/versions`),
  ])

  if (detailRes.status === 'fulfilled') {
    applyConfig(detailRes.value.config)
    detailWarnings.value = detailRes.value.warnings ?? []
    promptInfo.value = detailRes.value.prompt ?? null
    promptDraft.value = promptInfo.value?.body || ''
  } else {
    loadError.value = `加载 Agent 配置失败：${errorMessage(detailRes.reason)}`
  }

  if (promptRes.status === 'fulfilled') {
    promptInfo.value = promptRes.value
    promptDraft.value = promptInfo.value?.body || ''
  } else if (!promptInfo.value) {
    promptInfo.value = { body: '', fallback: true, version: null }
  }

  if (skillsRes.status === 'fulfilled') skills.value = skillsRes.value?.skills ?? []
  if (allSkillsRes.status === 'fulfilled') allSkills.value = allSkillsRes.value?.skills ?? []
  if (statsRes.status === 'fulfilled') stats.value = statsRes.value
  if (profilesRes.status === 'fulfilled') profiles.value = profilesRes.value?.profiles ?? []
  if (presetsRes.status === 'fulfilled') presets.value = presetsRes.value?.presets ?? []
  if (versionsRes.status === 'fulfilled') promptVersions.value = versionsRes.value?.versions ?? []
  const bound = (detailRes.status === 'fulfilled'
    ? (detailRes.value.config as unknown as { preset_id?: number | null }).preset_id
    : null)
  presetId.value = bound ?? null

  loading.value = false
}

async function save(): Promise<void> {
  const config = form.value
  if (!config) return
  saveError.value = ''
  let budget: Record<string, unknown>
  try {
    const parsed = budgetText.value.trim() ? JSON.parse(budgetText.value) : {}
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('预算覆盖必须是 JSON 对象')
    }
    budget = parsed as Record<string, unknown>
  } catch (e) {
    saveError.value = `预算 JSON 解析失败：${errorMessage(e)}`
    return
  }

  let ab: Record<string, unknown>
  try {
    const parsed = abText.value.trim() ? JSON.parse(abText.value) : {}
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('A/B 必须是 JSON 对象')
    }
    ab = parsed as Record<string, unknown>
  } catch (e) {
    saveError.value = `A/B JSON 解析失败：${errorMessage(e)}`
    return
  }

  const capabilities = {
    ...(config.capabilities || {}),
    engines: enginesText.value
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean),
  }

  const payload: Record<string, unknown> = {
    enabled: config.enabled !== false,
    display_name: config.display_name || '',
    model_role: config.model_role || 'fast',
    llm_profile_id: config.llm_profile_id ?? null,
    capabilities,
    timeout_s: config.timeout_s ?? 120,
    max_iterations: config.max_iterations ?? 8,
    temperature_override: temperature.value,
    budget_override: budget,
    ab_json: ab,
    tools_allow: config.tools_allow || [],
    skills_allow: config.skills_allow || [],
    wrapup_prompt: config.wrapup_prompt || '',
  }

  saving.value = true
  try {
    await api.put(`/api/agents/${agentName.value}`, payload)
    ElMessage.success('Agent 配置已保存')
    await load()
  } catch (e) {
    saveError.value = `保存失败：${errorMessage(e)}`
  } finally {
    saving.value = false
  }
}

async function savePrompt(): Promise<void> {
  if (!promptDraft.value.trim()) {
    ElMessage.warning('Prompt 不能为空')
    return
  }
  promptSaving.value = true
  try {
    await api.post('/api/prompts', {
      name: agentName.value,
      body: promptDraft.value,
      note: 'agent detail editor',
    })
    ElMessage.success('Prompt 新版本已创建并激活')
    await load()
  } catch (e) {
    ElMessage.error(`保存 Prompt 失败：${errorMessage(e)}`)
  } finally {
    promptSaving.value = false
  }
}

async function bindPreset(): Promise<void> {
  if (!presetId.value) {
    ElMessage.warning('请选择 preset')
    return
  }
  try {
    await api.post(`/api/agents/${agentName.value}/bind-preset`, { preset_id: presetId.value })
    ElMessage.success('Preset 已绑定')
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function unbindPreset(): Promise<void> {
  try {
    await api.post(`/api/agents/${agentName.value}/bind-preset`, { preset_id: null })
    presetId.value = null
    ElMessage.success('已解绑')
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

function openPresetDialog(): void {
  Object.assign(presetForm, { name: '', description: '', system_prompt: '', tools: '', skills: '' })
  presetDialog.value = true
}

async function createPreset(): Promise<void> {
  presetSaving.value = true
  try {
    await api.post('/api/agent-presets', {
      name: presetForm.name,
      base_agent: agentName.value,
      description: presetForm.description,
      system_prompt: presetForm.system_prompt,
      tools_allow: presetForm.tools.split(',').map((x) => x.trim()).filter(Boolean),
      skills_allow: presetForm.skills.split(',').map((x) => x.trim()).filter(Boolean),
    })
    ElMessage.success('Preset 已创建')
    presetDialog.value = false
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    presetSaving.value = false
  }
}

async function runCompare(): Promise<void> {
  comparing.value = true
  compareResult.value = null
  try {
    compareResult.value = await api.post<CompareResult>(
      `/api/agents/${agentName.value}/compare`,
      {
        prompt_a: compareA.value,
        prompt_b: compareB.value,
        use_llm: compareUseLlm.value,
      },
    )
    compareVisible.value = true
  } catch (e) {
    ElMessage.error(`对比失败：${errorMessage(e)}`)
  } finally {
    comparing.value = false
  }
}

async function dryRun(): Promise<void> {
  dryRunning.value = true
  try {
    dryRunResult.value = await api.post<Record<string, unknown>>(
      `/api/agents/${agentName.value}/dry-run`,
      {},
    )
    dryRunVisible.value = true
  } catch (e) {
    ElMessage.error(`Dry-run 失败：${errorMessage(e)}`)
  } finally {
    dryRunning.value = false
  }
}

async function previewPrompt(): Promise<void> {
  previewing.value = true
  try {
    previewResult.value = await api.post<Record<string, unknown>>(
      `/api/agents/${agentName.value}/preview-prompt`,
      {},
    )
    previewVisible.value = true
  } catch (e) {
    ElMessage.error(`预览失败：${errorMessage(e)}`)
  } finally {
    previewing.value = false
  }
}

watch(agentName, () => void load())
onMounted(load)
</script>

<style scoped>
.capability-grid {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
}

.prompt-preview {
  max-height: 220px;
}
</style>
