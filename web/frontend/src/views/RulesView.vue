<template>
  <div>
    <page-header title="规则管理" subtitle="Semgrep 规则列表、详情、YAML 校验与版本保存">
      <template #actions>
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
      </template>
    </page-header>

    <error-alert :message="error" @retry="load" />

    <el-row :gutter="18">
      <el-col :xs="24" :lg="13">
        <div class="panel">
          <h2 class="panel-title">
            规则列表 <span class="panel-subtitle">rules/codesentry-core.yml</span>
          </h2>
          <el-table v-loading="loading" :data="rules" row-key="id" size="small" max-height="620">
            <el-table-column prop="id" label="规则 ID" min-width="220" show-overflow-tooltip />
            <el-table-column label="语言" width="120">
              <template #default="{ row }">
                <span class="mono">{{ (row.languages || []).join(', ') || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="严重度" width="95">
              <template #default="{ row }"><status-tag :status="row.severity" /></template>
            </el-table-column>
            <el-table-column prop="cwe" label="CWE" width="100" show-overflow-tooltip />
            <el-table-column prop="message" label="描述" min-width="200" show-overflow-tooltip />
            <el-table-column label="操作" width="100" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openRule(row)">详情</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty
                :image-size="80"
                description="未读取到规则（rules/codesentry-core.yml 不存在或为空）"
              />
            </template>
          </el-table>
        </div>
      </el-col>

      <el-col :xs="24" :lg="11">
        <div class="panel">
          <div class="toolbar">
            <h2 class="panel-title" style="margin: 0">YAML 编辑与校验</h2>
            <div class="grow" />
            <el-upload :auto-upload="false" :show-file-list="false" accept=".yml,.yaml" :on-change="readFile">
              <el-button size="small">载入文件</el-button>
            </el-upload>
            <el-button size="small" :loading="validating" :disabled="!yamlText.trim()" @click="validate">
              校验
            </el-button>
            <el-button
              size="small"
              type="primary"
              :loading="saving"
              :disabled="!yamlText.trim()"
              @click="save"
            >
              保存版本
            </el-button>
          </div>

          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="后端未提供原始 YAML 读取接口；请粘贴或载入完整 YAML 后再校验/保存。保存会写入 rule_sets 新版本与 rules/codesentry-core.yml。"
            style="margin-bottom: 10px"
          />

          <el-input
            v-model="yamlText"
            class="code-input"
            type="textarea"
            :rows="22"
            placeholder="rules:&#10;  - id: codesentry.python.sql-injection&#10;    languages: [python]&#10;    severity: ERROR&#10;    message: ..."
          />

          <div v-if="validation" style="margin-top: 12px">
            <el-alert
              :type="validation.ok ? 'success' : 'error'"
              :title="validation.ok ? 'Semgrep 校验通过' : 'Semgrep 校验未通过'"
              :closable="false"
              show-icon
            />
            <pre v-if="validation.output" class="pre-block light" style="margin-top: 8px">{{ validation.output }}</pre>
          </div>
          <el-alert
            v-if="actionError"
            type="error"
            :title="actionError"
            :closable="false"
            show-icon
            style="margin-top: 12px"
          />
          <el-alert
            v-if="saveMessage"
            type="success"
            :title="saveMessage"
            :closable="false"
            show-icon
            style="margin-top: 12px"
          />
        </div>
      </el-col>
    </el-row>

    <el-drawer v-model="detailVisible" :title="detailRule?.id || '规则详情'" size="55%">
      <el-descriptions v-if="detailRule" :column="2" border size="small" style="margin-bottom: 14px">
        <el-descriptions-item label="ID" :span="2">{{ detailRule.id }}</el-descriptions-item>
        <el-descriptions-item label="语言">
          {{ languagesText(detailRule.languages) }}
        </el-descriptions-item>
        <el-descriptions-item label="严重度">{{ detailRule.severity || '—' }}</el-descriptions-item>
        <el-descriptions-item label="消息" :span="2">{{ detailRule.message || '—' }}</el-descriptions-item>
      </el-descriptions>
      <error-alert :message="detailError" :retryable="false" />
      <json-block v-if="detailRule" :value="detailRule" />
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { UploadFile } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { api, errorMessage } from '@/api/client'
import type { RuleSummary } from '@/api/types'
import ErrorAlert from '@/components/ErrorAlert.vue'
import JsonBlock from '@/components/JsonBlock.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'

interface Validation {
  ok: boolean
  output?: string
}

const loading = ref(false)
const error = ref('')
const rules = ref<RuleSummary[]>([])

const yamlText = ref('')
const validating = ref(false)
const saving = ref(false)
const validation = ref<Validation | null>(null)
const actionError = ref('')
const saveMessage = ref('')

const detailVisible = ref(false)
const detailRule = ref<Record<string, unknown> | null>(null)
const detailError = ref('')

function languagesText(value: unknown): string {
  return Array.isArray(value) ? value.join(', ') : '—'
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const res = await api.get<{ rules: RuleSummary[] }>('/api/rules')
    rules.value = res?.rules ?? []
  } catch (e) {
    error.value = `加载规则失败：${errorMessage(e)}`
  } finally {
    loading.value = false
  }
}

function readFile(file: UploadFile): void {
  const raw = file.raw
  if (!raw) return
  const reader = new FileReader()
  reader.onload = () => {
    yamlText.value = String(reader.result || '')
    validation.value = null
    actionError.value = ''
    saveMessage.value = ''
  }
  reader.readAsText(raw)
}

async function validate(): Promise<boolean> {
  validating.value = true
  actionError.value = ''
  saveMessage.value = ''
  try {
    validation.value = await api.post<Validation>('/api/rules/validate', { yaml: yamlText.value })
    return validation.value.ok
  } catch (e) {
    actionError.value = errorMessage(e)
    return false
  } finally {
    validating.value = false
  }
}

async function save(): Promise<void> {
  saving.value = true
  actionError.value = ''
  saveMessage.value = ''
  try {
    const res = await api.post<{ ok: boolean; version: number }>('/api/rules/save', {
      yaml: yamlText.value,
    })
    saveMessage.value = `规则已保存为版本 v${res.version}`
    ElMessage.success(saveMessage.value)
    await load()
  } catch (e) {
    actionError.value = `保存失败：${errorMessage(e)}`
  } finally {
    saving.value = false
  }
}

async function openRule(row: RuleSummary): Promise<void> {
  detailVisible.value = true
  detailRule.value = null
  detailError.value = ''
  try {
    const res = await api.get<{ rule: Record<string, unknown> }>(
      `/api/rules/${encodeURIComponent(row.id)}`,
    )
    detailRule.value = res?.rule ?? null
  } catch (e) {
    detailError.value = `加载规则详情失败：${errorMessage(e)}`
  }
}

onMounted(load)
</script>
