<template>
  <div>
    <page-header
      title="LLM 配置"
      subtitle="多 Provider 配置、连通性测试、模型探测与默认路由"
    >
      <template #actions>
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
        <el-button type="primary" @click="openCreate()">新建 Profile</el-button>
      </template>
    </page-header>

    <error-alert :message="error" @retry="load" />

    <div class="panel">
      <el-table v-loading="loading" :data="profiles" row-key="id">
        <el-table-column label="名称" min-width="160">
          <template #default="{ row }">
            <div>
              <strong>{{ row.name }}</strong>
              <el-tag v-if="row.is_default" size="small" type="success" style="margin-left: 6px">
                默认
              </el-tag>
              <el-tag v-if="row.enabled === false" size="small" type="info" style="margin-left: 6px">
                停用
              </el-tag>
            </div>
            <div class="mono muted">#{{ row.id }} · {{ row.provider }}</div>
          </template>
        </el-table-column>
        <el-table-column label="协议 / 地址" min-width="240">
          <template #default="{ row }">
            <div>{{ row.protocol }}</div>
            <div class="mono muted">{{ row.base_url }}</div>
          </template>
        </el-table-column>
        <el-table-column label="模型" min-width="190">
          <template #default="{ row }">
            <div class="mono">fast: {{ row.fast_model || '—' }}</div>
            <div class="mono">deep: {{ row.deep_model || '—' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="API Key" width="150">
          <template #default="{ row }">
            <span class="mono">{{ row.api_key || '（未设置）' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="绑定 Agent" min-width="150">
          <template #default="{ row }">
            <div v-if="row.bound_agents?.length" class="inline-tags">
              <el-tag v-for="agent in row.bound_agents" :key="agent" size="small" effect="plain">
                {{ agent }}
              </el-tag>
            </div>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="290" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link @click="testProfile(row)">测试</el-button>
            <el-button link @click="probeProfile(row)">探测</el-button>
            <el-button link :disabled="row.is_default" @click="makeDefault(row)">设为默认</el-button>
            <el-button link type="danger" @click="removeProfile(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty
            :image-size="80"
            description="还没有 LLM Profile。可新建，或直接使用环境变量中的全局 LLM。"
          >
            <el-button type="primary" @click="openCreate()">新建 Profile</el-button>
          </el-empty>
        </template>
      </el-table>
    </div>

    <div class="panel">
      <h2 class="panel-title">池与健康 <span class="panel-subtitle">激活配置链首 → priority 降序</span></h2>
      <el-table :data="health" size="small">
        <el-table-column prop="name" label="Profile" min-width="140" />
        <el-table-column prop="priority" label="优先级" width="80" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.open ? 'danger' : 'success'">
              {{ row.open ? '冷却中' : '可用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="fails" label="连续失败" width="90" />
        <el-table-column prop="trips" label="熔断次数" width="90" />
        <el-table-column prop="last_error" label="最近错误" min-width="240" show-overflow-tooltip />
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button link type="primary" :disabled="!row.open" @click="recover(row.profile_id)">
              恢复
            </el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty :image-size="50" description="暂无健康数据" /></template>
      </el-table>
    </div>

    <div class="panel">
      <h2 class="panel-title">最近调用 <span class="panel-subtitle">原始请求/响应已脱敏截断</span></h2>
      <el-table :data="calls" size="small" max-height="320">
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="agent" label="Agent" width="100" />
        <el-table-column prop="model" label="模型" min-width="150" show-overflow-tooltip />
        <el-table-column label="token" width="110">
          <template #default="{ row }">{{ row.prompt_tokens }} / {{ row.completion_tokens }}</template>
        </el-table-column>
        <el-table-column prop="latency_ms" label="耗时 ms" width="90" />
        <el-table-column label="结果" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.ok ? 'success' : 'danger'">{{ row.ok ? 'OK' : 'ERR' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="error" label="错误" min-width="180" show-overflow-tooltip />
        <el-table-column prop="created_at" label="时间" min-width="160" show-overflow-tooltip />
        <template #empty><el-empty :image-size="50" description="暂无调用记录" /></template>
      </el-table>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? `编辑 Profile #${editingId}` : '新建 LLM Profile'"
      width="780px"
      destroy-on-close
    >
      <el-alert v-if="dialogError" type="error" :title="dialogError" :closable="false" show-icon style="margin-bottom: 12px" />
      <el-form label-position="top">
        <el-row :gutter="14">
          <el-col :xs="24" :sm="12">
            <el-form-item label="预设（可选）">
              <el-select
                v-model="presetKey"
                clearable
                placeholder="选择预设以填充地址与协议"
                style="width: 100%"
                @change="applyPreset"
              >
                <el-option v-for="key in Object.keys(presets)" :key="key" :label="key" :value="key" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="名称 *">
              <el-input v-model="form.name" placeholder="prod-openai" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="Provider">
              <el-input v-model="form.provider" placeholder="openai-compatible" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="Protocol">
              <el-select v-model="form.protocol" style="width: 100%">
                <el-option label="openai-compatible" value="openai-compatible" />
                <el-option label="anthropic-compatible" value="anthropic-compatible" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="16">
            <el-form-item label="Base URL *">
              <el-input v-model="form.base_url" placeholder="https://api.openai.com/v1" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="8">
            <el-form-item label="Billing Mode">
              <el-select v-model="form.billing_mode" style="width: 100%">
                <el-option label="metered" value="metered" />
                <el-option label="subscription" value="subscription" />
                <el-option label="local" value="local" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="API Key">
              <el-input
                v-model="form.api_key"
                type="password"
                show-password
                :placeholder="editingId ? '留空表示保留现有密钥' : 'sk-...'"
              />
              <div class="muted" style="font-size: 12px; margin-top: 4px">
                {{ editingId ? '只写不读；列表中的值是服务端掩码。' : '写入后由服务端加密存储。' }}
              </div>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="模型前缀策略">
              <el-select v-model="form.model_prefix_policy" style="width: 100%">
                <el-option label="strip" value="strip" />
                <el-option label="keep" value="keep" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="Fast Model">
              <el-input v-model="form.fast_model" placeholder="gpt-4o-mini" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="Deep Model">
              <el-input v-model="form.deep_model" placeholder="gpt-4o" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="温度">
              <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="Max Tokens">
              <el-input-number v-model="form.max_tokens" :min="0" :step="256" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="超时 (s)">
              <el-input-number v-model="form.timeout_s" :min="1" :max="600" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="最大并发">
              <el-input-number v-model="form.max_concurrency" :min="1" :max="64" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="输入价 / 1K">
              <el-input-number v-model="form.input_price_per_1k" :min="0" :step="0.0001" :precision="6" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="输出价 / 1K">
              <el-input-number v-model="form.output_price_per_1k" :min="0" :step="0.0001" :precision="6" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="启用">
              <el-switch v-model="form.enabled" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="设为默认">
              <el-switch v-model="form.is_default" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="池优先级">
              <el-input-number v-model="form.priority" :min="0" :max="1000" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="上下文窗口 (K)">
              <el-input-number v-model="form.context_window_k" :min="0" :max="2000" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="不参与故障转移">
              <el-switch v-model="form.pool_exclude" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-collapse>
          <el-collapse-item title="高级 JSON（capabilities / headers / 模型目录 / 配额）" name="advanced">
            <el-form-item label="capabilities">
              <el-input v-model="advanced.capabilities" class="code-input" type="textarea" :rows="3" />
            </el-form-item>
            <el-form-item label="extra_headers">
              <el-input v-model="advanced.extra_headers" class="code-input" type="textarea" :rows="3" />
            </el-form-item>
            <el-form-item label="model_catalog">
              <el-input v-model="advanced.model_catalog" class="code-input" type="textarea" :rows="3" />
            </el-form-item>
            <el-form-item label="model_protocols">
              <el-input v-model="advanced.model_protocols" class="code-input" type="textarea" :rows="3" />
            </el-form-item>
            <el-form-item label="quota_windows">
              <el-input v-model="advanced.quota_windows" class="code-input" type="textarea" :rows="3" />
            </el-form-item>
          </el-collapse-item>
        </el-collapse>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="resultVisible" :title="resultTitle" width="680px">
      <pre class="pre-block light">{{ resultText }}</pre>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { api, errorMessage } from '@/api/client'
import type { LlmProfile } from '@/api/types'
import ErrorAlert from '@/components/ErrorAlert.vue'
import PageHeader from '@/components/PageHeader.vue'

interface Preset {
  provider?: string
  protocol?: string
  base_url?: string
  billing_mode?: string
  model_prefix_policy?: string
  extra_headers?: Record<string, string>
  quota_windows?: unknown[]
}

const loading = ref(false)
const error = ref('')
const profiles = ref<LlmProfile[]>([])
const presets = ref<Record<string, Preset>>({})
const health = ref<Array<Record<string, unknown>>>([])
const calls = ref<Array<Record<string, unknown>>>([])

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const presetKey = ref('')
const saving = ref(false)
const dialogError = ref('')

const form = reactive({
  name: '',
  provider: 'openai-compatible',
  protocol: 'openai-compatible',
  model_prefix_policy: 'strip',
  base_url: '',
  api_key: '',
  fast_model: '',
  deep_model: '',
  temperature: 0,
  max_tokens: 0,
  timeout_s: 60,
  max_concurrency: 4,
  input_price_per_1k: 0,
  output_price_per_1k: 0,
  billing_mode: 'metered',
  enabled: true,
  is_default: false,
  priority: 0,
  pool_exclude: false,
  context_window_k: 0,
})

const advanced = reactive({
  capabilities: '{}',
  extra_headers: '{}',
  model_catalog: '[]',
  model_protocols: '{}',
  quota_windows: '[]',
})

const resultVisible = ref(false)
const resultTitle = ref('')
const resultText = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  const [profilesRes, presetsRes] = await Promise.allSettled([
    api.get<{ profiles: LlmProfile[] }>('/api/llm-profiles'),
    api.get<{ presets: Record<string, Preset> }>('/api/llm-profiles/presets'),
  ])
  if (profilesRes.status === 'fulfilled') profiles.value = profilesRes.value?.profiles ?? []
  else error.value = `加载 LLM Profiles 失败：${errorMessage(profilesRes.reason)}`
  if (presetsRes.status === 'fulfilled') presets.value = presetsRes.value?.presets ?? {}
  void loadHealth()
  void loadCalls()
  loading.value = false
}

async function loadHealth(): Promise<void> {
  try {
    const res = await api.get<{ profiles?: Array<Record<string, unknown>> }>('/api/llm-profiles/health')
    health.value = res.profiles || []
  } catch {
    health.value = []
  }
}

async function loadCalls(): Promise<void> {
  try {
    const res = await api.get<{ calls?: Array<Record<string, unknown>> }>('/api/llm-calls', { limit: 20 })
    calls.value = res.calls || []
  } catch {
    calls.value = []
  }
}

async function recover(profileId: number): Promise<void> {
  try {
    await api.post(`/api/llm-profiles/${profileId}/recover`, {})
    ElMessage.success('已恢复该 Profile')
    void loadHealth()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

function resetForm(): void {
  Object.assign(form, {
    name: '',
    provider: 'openai-compatible',
    protocol: 'openai-compatible',
    model_prefix_policy: 'strip',
    base_url: '',
    api_key: '',
    fast_model: '',
    deep_model: '',
    temperature: 0,
    max_tokens: 0,
    timeout_s: 60,
    max_concurrency: 4,
    input_price_per_1k: 0,
    output_price_per_1k: 0,
    billing_mode: 'metered',
    enabled: true,
    is_default: false,
    priority: 0,
    pool_exclude: false,
    context_window_k: 0,
  })
  Object.assign(advanced, {
    capabilities: '{}',
    extra_headers: '{}',
    model_catalog: '[]',
    model_protocols: '{}',
    quota_windows: '[]',
  })
  presetKey.value = ''
  dialogError.value = ''
}

function openCreate(): void {
  editingId.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(profile: LlmProfile): void {
  editingId.value = profile.id
  resetForm()
  Object.assign(form, {
    name: profile.name ?? '',
    provider: profile.provider ?? 'openai-compatible',
    protocol: profile.protocol ?? 'openai-compatible',
    model_prefix_policy: profile.model_prefix_policy ?? 'strip',
    base_url: profile.base_url ?? '',
    api_key: '',
    fast_model: profile.fast_model ?? '',
    deep_model: profile.deep_model ?? '',
    temperature: Number(profile.temperature ?? 0),
    max_tokens: Number(profile.max_tokens ?? 0),
    timeout_s: Number(profile.timeout_s ?? 60),
    max_concurrency: Number(profile.max_concurrency ?? 4),
    input_price_per_1k: Number(profile.input_price_per_1k ?? 0),
    output_price_per_1k: Number(profile.output_price_per_1k ?? 0),
    billing_mode: profile.billing_mode ?? 'metered',
    enabled: profile.enabled !== false,
    is_default: profile.is_default === true,
    priority: Number(profile.priority ?? 0),
    pool_exclude: profile.pool_exclude === true,
    context_window_k: Number(profile.context_window_k ?? 0),
  })
  advanced.capabilities = JSON.stringify(profile.capabilities ?? {}, null, 2)
  advanced.extra_headers = JSON.stringify(profile.extra_headers ?? {}, null, 2)
  advanced.model_catalog = JSON.stringify(profile.model_catalog ?? [], null, 2)
  advanced.model_protocols = JSON.stringify(profile.model_protocols ?? {}, null, 2)
  advanced.quota_windows = JSON.stringify(profile.quota_windows ?? [], null, 2)
  dialogVisible.value = true
}

function applyPreset(key: string): void {
  const preset = presets.value[key]
  if (!preset) return
  if (preset.provider) form.provider = preset.provider
  if (preset.protocol) form.protocol = preset.protocol
  if (preset.base_url !== undefined) form.base_url = preset.base_url
  if (preset.billing_mode) form.billing_mode = preset.billing_mode
  if (preset.model_prefix_policy) form.model_prefix_policy = preset.model_prefix_policy
  if (preset.extra_headers) advanced.extra_headers = JSON.stringify(preset.extra_headers, null, 2)
  if (preset.quota_windows) advanced.quota_windows = JSON.stringify(preset.quota_windows, null, 2)
}

function parseJson(text: string, label: string): unknown {
  try {
    return text.trim() ? JSON.parse(text) : undefined
  } catch (e) {
    throw new Error(`${label} 不是合法 JSON：${errorMessage(e)}`)
  }
}

async function save(): Promise<void> {
  dialogError.value = ''
  if (!form.name.trim()) {
    dialogError.value = '请填写 Profile 名称'
    return
  }
  if (!form.base_url.trim()) {
    dialogError.value = '请填写 Base URL'
    return
  }
  let payload: Record<string, unknown>
  try {
    payload = {
      name: form.name.trim(),
      provider: form.provider,
      protocol: form.protocol,
      model_prefix_policy: form.model_prefix_policy,
      base_url: form.base_url.trim(),
      fast_model: form.fast_model,
      deep_model: form.deep_model,
      temperature: form.temperature,
      max_tokens: form.max_tokens,
      timeout_s: form.timeout_s,
      max_concurrency: form.max_concurrency,
      input_price_per_1k: form.input_price_per_1k,
      output_price_per_1k: form.output_price_per_1k,
      billing_mode: form.billing_mode,
      enabled: form.enabled,
      is_default: form.is_default,
      priority: form.priority,
      pool_exclude: form.pool_exclude,
      context_window_k: form.context_window_k,
      capabilities: parseJson(advanced.capabilities, 'capabilities'),
      extra_headers: parseJson(advanced.extra_headers, 'extra_headers'),
      model_catalog: parseJson(advanced.model_catalog, 'model_catalog'),
      model_protocols: parseJson(advanced.model_protocols, 'model_protocols'),
      quota_windows: parseJson(advanced.quota_windows, 'quota_windows'),
    }
    if (form.api_key.trim()) payload.api_key = form.api_key.trim()
    else if (!editingId.value) payload.api_key = ''
  } catch (e) {
    dialogError.value = errorMessage(e)
    return
  }

  saving.value = true
  try {
    if (editingId.value) {
      await api.put(`/api/llm-profiles/${editingId.value}`, payload)
      ElMessage.success('Profile 已更新')
    } else {
      await api.post('/api/llm-profiles', payload)
      ElMessage.success('Profile 已创建')
    }
    dialogVisible.value = false
    await load()
  } catch (e) {
    dialogError.value = errorMessage(e)
  } finally {
    saving.value = false
  }
}

function showResult(title: string, value: unknown): void {
  resultTitle.value = title
  resultText.value = JSON.stringify(value, null, 2)
  resultVisible.value = true
}

async function testProfile(profile: LlmProfile): Promise<void> {
  const loadingMessage = ElMessage({ message: `正在测试 ${profile.name}…`, duration: 0 })
  try {
    const res = await api.post<Record<string, unknown>>(`/api/llm-profiles/${profile.id}/test`)
    showResult(`连通性测试 · ${profile.name}`, res)
  } catch (e) {
    showResult(`连通性测试 · ${profile.name}`, { ok: false, error: errorMessage(e) })
  } finally {
    loadingMessage.close()
  }
}

async function probeProfile(profile: LlmProfile): Promise<void> {
  const loadingMessage = ElMessage({ message: `正在探测 ${profile.name}…`, duration: 0 })
  try {
    const res = await api.post<Record<string, unknown>>(
      `/api/llm-profiles/${profile.id}/probe`,
      undefined,
      { query: { limit: 5 } },
    )
    showResult(`模型探测 · ${profile.name}`, res)
    await load()
  } catch (e) {
    showResult(`模型探测 · ${profile.name}`, { ok: false, error: errorMessage(e) })
  } finally {
    loadingMessage.close()
  }
}

async function makeDefault(profile: LlmProfile): Promise<void> {
  try {
    await api.post(`/api/llm-profiles/${profile.id}/default`)
    ElMessage.success(`${profile.name} 已设为默认 Profile`)
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function removeProfile(profile: LlmProfile): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认删除 LLM Profile「${profile.name}」？仍被 Agent 绑定时后端会拒绝。`,
      '删除 Profile',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await api.del(`/api/llm-profiles/${profile.id}`)
    ElMessage.success('Profile 已删除')
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

onMounted(load)
</script>
