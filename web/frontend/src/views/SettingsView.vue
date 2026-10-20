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
  await Promise.all([loadGroup('llm'), loadGroup('embedding')])
  loading.value = false
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
