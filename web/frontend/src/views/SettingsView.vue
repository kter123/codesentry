<template>
  <div>
    <page-header title="全局设置" subtitle="全局兜底 LLM 与 Embedding 配置（密钥仅掩码回显）">
      <template #actions>
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
      </template>
    </page-header>

    <el-row :gutter="18">
      <el-col :xs="24" :lg="12">
        <div class="panel">
          <h2 class="panel-title">LLM 兜底配置</h2>
          <el-alert
            v-if="errors.llm"
            type="error"
            :title="errors.llm"
            :closable="false"
            show-icon
            style="margin-bottom: 10px"
          />
          <el-form label-position="top" :disabled="loading">
            <el-form-item label="Base URL">
              <el-input v-model="llm.model_base_url" placeholder="https://api.openai.com/v1" />
            </el-form-item>
            <el-form-item label="API Key">
              <el-input v-model="llm.model_api_key" type="password" show-password />
              <el-checkbox v-model="clearKeys.llm" style="margin-top: 6px">
                清空已保存的 API Key
              </el-checkbox>
            </el-form-item>
            <el-form-item label="Fast Model">
              <el-input v-model="llm.fast_model" placeholder="gpt-4o-mini" />
            </el-form-item>
            <el-form-item label="Deep Model">
              <el-input v-model="llm.deep_model" placeholder="gpt-4o" />
            </el-form-item>
          </el-form>
          <div class="toolbar" style="margin-bottom: 0">
            <el-button type="primary" :loading="saving.llm" @click="save('llm')">保存</el-button>
            <el-button :loading="testing.llm" @click="test('llm')">测试连接</el-button>
          </div>
          <el-alert
            v-if="testResults.llm"
            :type="testResults.llm.ok ? 'success' : 'error'"
            :title="testResults.llm.text"
            :closable="false"
            show-icon
            style="margin-top: 12px"
          />
        </div>
      </el-col>

      <el-col :xs="24" :lg="12">
        <div class="panel">
          <h2 class="panel-title">Embedding 配置</h2>
          <el-alert
            v-if="errors.embedding"
            type="error"
            :title="errors.embedding"
            :closable="false"
            show-icon
            style="margin-bottom: 10px"
          />
          <el-form label-position="top" :disabled="loading">
            <el-form-item label="Base URL">
              <el-input v-model="embedding.embedding_base_url" placeholder="https://api.openai.com/v1" />
            </el-form-item>
            <el-form-item label="API Key">
              <el-input v-model="embedding.embedding_api_key" type="password" show-password />
              <el-checkbox v-model="clearKeys.embedding" style="margin-top: 6px">
                清空已保存的 API Key
              </el-checkbox>
            </el-form-item>
            <el-form-item label="Embedding Model">
              <el-input v-model="embedding.embedding_model" placeholder="text-embedding-3-small" />
            </el-form-item>
          </el-form>
          <div class="toolbar" style="margin-bottom: 0">
            <el-button type="primary" :loading="saving.embedding" @click="save('embedding')">
              保存
            </el-button>
            <el-button :loading="testing.embedding" @click="test('embedding')">测试连接</el-button>
          </div>
          <el-alert
            v-if="testResults.embedding"
            :type="testResults.embedding.ok ? 'success' : 'error'"
            :title="testResults.embedding.text"
            :closable="false"
            show-icon
            style="margin-top: 12px"
          />
        </div>

        <div class="panel">
          <h2 class="panel-title">说明</h2>
          <div class="muted" style="font-size: 13px; line-height: 1.8">
            这里的配置是全局兜底：当 Agent 未绑定 LLM Profile 且没有默认 Profile 时生效。
            API Key 在服务端加密存储，读取接口只返回掩码；保存时留空（且未勾选清空）表示保留原值。
          </div>
        </div>
      </el-col>
    </el-row>

    <div class="panel">
      <h2 class="panel-title">CodeQL 引擎</h2>
      <el-alert
        v-if="codeqlResult"
        :type="codeqlResult.ok ? 'success' : 'error'"
        :title="codeqlResult.text"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      />
      <el-form label-position="top" :disabled="loading">
        <el-row :gutter="14">
          <el-col :xs="24" :sm="12">
            <el-form-item label="Binary（留空自动探测）">
              <el-input v-model="codeql.codeql_bin" placeholder="~/.codesentry/tools/codeql/codeql" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="Query packs 搜索路径">
              <el-input v-model="codeql.codeql_search_path" placeholder="~/.codeql/packages" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="Suite（支持 {lang}）">
              <el-input v-model="codeql.codeql_suite" placeholder="codeql/{lang}-queries:codeql-suites/{lang}-security-extended.qls" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="Build mode">
              <el-select v-model="codeql.codeql_build_mode" style="width: 100%">
                <el-option label="none" value="none" />
                <el-option label="autobuild" value="autobuild" />
                <el-option label="manual" value="manual" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="Timeout (s)">
              <el-input-number v-model="codeql.timeout" :min="60" :max="7200" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="18">
            <el-form-item label="Build command（仅 manual）">
              <el-input
                v-model="codeql.codeql_build_command"
                :disabled="codeql.codeql_build_mode !== 'manual'"
                placeholder="mvn -q -DskipTests package"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="6">
            <el-form-item label="DB cache">
              <el-switch v-model="codeql.cache" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <div class="toolbar" style="margin-bottom: 0">
        <el-button type="primary" :loading="codeqlSaving" @click="saveCodeql">保存</el-button>
        <el-button :loading="codeqlTesting" @click="testCodeql">探测</el-button>
        <span v-if="codeqlStatus?.found" class="muted">
          {{ codeqlStatus.version || '已安装' }} · {{ codeqlStatus.binary }}
        </span>
        <span v-else class="muted">未检测到 CodeQL（可填写 binary 或安装到默认目录）</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { api, errorMessage } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'

type Group = 'llm' | 'embedding'

interface LlmForm {
  model_base_url: string
  model_api_key: string
  fast_model: string
  deep_model: string
}

interface EmbeddingForm {
  embedding_base_url: string
  embedding_api_key: string
  embedding_model: string
}

const loading = ref(false)
const llm = reactive<LlmForm>({
  model_base_url: '',
  model_api_key: '',
  fast_model: '',
  deep_model: '',
})
const embedding = reactive<EmbeddingForm>({
  embedding_base_url: '',
  embedding_api_key: '',
  embedding_model: '',
})
const loadedValues = {
  llm: { ...llm } as Record<string, string>,
  embedding: { ...embedding } as Record<string, string>,
}
const clearKeys = reactive<Record<Group, boolean>>({ llm: false, embedding: false })
const errors = reactive<Record<Group, string>>({ llm: '', embedding: '' })
const saving = reactive<Record<Group, boolean>>({ llm: false, embedding: false })
const testing = reactive<Record<Group, boolean>>({ llm: false, embedding: false })
const testResults = reactive<Record<Group, { ok: boolean; text: string } | null>>({
  llm: null,
  embedding: null,
})
const codeql = reactive({
  codeql_bin: '',
  codeql_search_path: '',
  codeql_suite: '',
  codeql_build_mode: 'none',
  codeql_build_command: '',
  timeout: 1800,
  cache: true,
})
const codeqlSaving = ref(false)
const codeqlTesting = ref(false)
const codeqlResult = ref<{ ok: boolean; text: string } | null>(null)
const codeqlStatus = ref<Record<string, unknown> | null>(null)

async function loadGroup(group: Group): Promise<void> {
  errors[group] = ''
  try {
    const res = await api.get<Record<string, string>>(`/api/settings/${group}`)
    if (group === 'llm') {
      Object.assign(llm, {
        model_base_url: res.model_base_url ?? '',
        model_api_key: res.model_api_key ?? '',
        fast_model: res.fast_model ?? '',
        deep_model: res.deep_model ?? '',
      })
      loadedValues.llm = { ...llm }
    } else {
      Object.assign(embedding, {
        embedding_base_url: res.embedding_base_url ?? '',
        embedding_api_key: res.embedding_api_key ?? '',
        embedding_model: res.embedding_model ?? '',
      })
      loadedValues.embedding = { ...embedding }
    }
  } catch (e) {
    errors[group] = `加载 ${group} 设置失败：${errorMessage(e)}`
  }
}

async function load(): Promise<void> {
  loading.value = true
  await Promise.all([loadGroup('llm'), loadGroup('embedding'), loadCodeql()])
  loading.value = false
}

async function loadCodeql(): Promise<void> {
  try {
    const [cfg, status] = await Promise.allSettled([
      api.get<Record<string, string>>('/api/settings/codeql'),
      api.get<Record<string, unknown>>('/api/engines/codeql/status'),
    ])
    if (cfg.status === 'fulfilled') {
      Object.assign(codeql, {
        codeql_bin: cfg.value.codeql_bin ?? '',
        codeql_search_path: cfg.value.codeql_search_path ?? '',
        codeql_suite: cfg.value.codeql_suite ?? '',
        codeql_build_mode: cfg.value.codeql_build_mode || 'none',
        codeql_build_command: cfg.value.codeql_build_command ?? '',
        timeout: Number(cfg.value.codeql_timeout_s || 1800),
        cache: (cfg.value.codeql_db_cache ?? 'true') !== 'false',
      })
    }
    codeqlStatus.value = status.status === 'fulfilled' ? status.value : null
  } catch {
    codeqlStatus.value = null
  }
}

async function saveCodeql(): Promise<void> {
  codeqlSaving.value = true
  codeqlResult.value = null
  try {
    await api.put('/api/settings/codeql', {
      values: {
        codeql_bin: codeql.codeql_bin,
        codeql_search_path: codeql.codeql_search_path,
        codeql_suite: codeql.codeql_suite,
        codeql_build_mode: codeql.codeql_build_mode,
        codeql_build_command: codeql.codeql_build_command,
        codeql_timeout_s: String(codeql.timeout),
        codeql_db_cache: codeql.cache ? 'true' : 'false',
      },
    })
    ElMessage.success('CodeQL 配置已保存')
    await loadCodeql()
  } catch (e) {
    codeqlResult.value = { ok: false, text: `保存失败：${errorMessage(e)}` }
  } finally {
    codeqlSaving.value = false
  }
}

async function testCodeql(): Promise<void> {
  codeqlTesting.value = true
  codeqlResult.value = null
  try {
    const res = await api.post<Record<string, unknown>>('/api/engines/codeql/test')
    codeqlStatus.value = res
    codeqlResult.value = {
      ok: Boolean(res.ok),
      text: res.ok
        ? `CodeQL ${res.version || ''}，语言：${(res.languages as string[] || []).join(', ') || '—'}`
        : `未检测到：${String(res.error || res.binary || '')}`,
    }
  } catch (e) {
    codeqlResult.value = { ok: false, text: `探测失败：${errorMessage(e)}` }
  } finally {
    codeqlTesting.value = false
  }
}

function buildValues(group: Group): Record<string, string> {
  if (group === 'llm') {
    const values: Record<string, string> = {
      model_base_url: llm.model_base_url,
      fast_model: llm.fast_model,
      deep_model: llm.deep_model,
    }
    if (clearKeys.llm) values.model_api_key = ''
    else if (llm.model_api_key !== loadedValues.llm.model_api_key && llm.model_api_key) {
      values.model_api_key = llm.model_api_key
    }
    return values
  }
  const values: Record<string, string> = {
    embedding_base_url: embedding.embedding_base_url,
    embedding_model: embedding.embedding_model,
  }
  if (clearKeys.embedding) values.embedding_api_key = ''
  else if (
    embedding.embedding_api_key !== loadedValues.embedding.embedding_api_key &&
    embedding.embedding_api_key
  ) {
    values.embedding_api_key = embedding.embedding_api_key
  }
  return values
}

async function save(group: Group): Promise<void> {
  saving[group] = true
  errors[group] = ''
  try {
    await api.put(`/api/settings/${group}`, { values: buildValues(group) })
    ElMessage.success(`${group} 设置已保存`)
    clearKeys[group] = false
    await loadGroup(group)
  } catch (e) {
    errors[group] = `保存失败：${errorMessage(e)}`
  } finally {
    saving[group] = false
  }
}

async function test(group: Group): Promise<void> {
  testing[group] = true
  testResults[group] = null
  try {
    const res = await api.post<Record<string, unknown>>(`/api/settings/${group}/test`)
    const ok = res?.ok === true
    testResults[group] = {
      ok,
      text: ok
        ? `${group} 连接成功：${JSON.stringify(res)}`
        : `${group} 连接失败：${String(res?.error || JSON.stringify(res))}`,
    }
  } catch (e) {
    testResults[group] = { ok: false, text: `测试请求失败：${errorMessage(e)}` }
  } finally {
    testing[group] = false
  }
}

onMounted(load)
</script>
