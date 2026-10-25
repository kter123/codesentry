<template>
  <div>
    <page-header title="编排模板" subtitle="LangGraph 节点链、边与中断点的校验、版本与激活">
      <template #actions>
        <el-button @click="resetTemplate">恢复默认</el-button>
        <el-button :loading="validating" @click="validateTemplate">校验</el-button>
        <el-button @click="saveDraft">保存本地草稿</el-button>
        <el-button type="primary" :loading="saving" @click="saveTemplate">保存到服务端</el-button>
      </template>
    </page-header>

    <el-alert
      v-if="backendNote"
      :type="backendOnline ? 'success' : 'info'"
      show-icon
      :closable="false"
      :title="backendNote"
      style="margin-bottom: 14px"
    />
    <el-alert
      v-if="actionError"
      type="error"
      show-icon
      :closable="false"
      :title="actionError"
      style="margin-bottom: 14px"
    />
    <el-alert
      v-if="validation && !validation.ok"
      type="error"
      show-icon
      :closable="false"
      title="模板校验未通过"
      style="margin-bottom: 14px"
    >
      <ul class="error-list">
        <li v-for="item in validation.errors" :key="item">{{ item }}</li>
      </ul>
    </el-alert>
    <el-alert
      v-if="validation && validation.ok"
      type="success"
      show-icon
      :closable="false"
      :title="`模板校验通过：${validation.nodes.length} 个节点`"
      style="margin-bottom: 14px"
    />

    <div class="panel">
      <h2 class="panel-title">默认节点链</h2>
      <div class="flow">
        <template v-for="(node, index) in defaultNodes" :key="node.id">
          <div class="flow-node" :class="{ sandbox: node.sandbox }">
            <div class="flow-node-label">{{ node.label }}</div>
            <div class="mono muted">{{ node.id }}</div>
          </div>
          <div v-if="index < defaultNodes.length - 1" class="flow-arrow">→</div>
        </template>
      </div>
      <div class="muted" style="margin-top: 10px; font-size: 12px">
        deploy 为 M6.1 引入的 Docker 沙箱节点；共同构成 recon → scan → retrieval → triage → deploy →
        poc_gen → report。human_review 为 triage 后可选中断点。
      </div>
    </div>

    <div class="panel">
      <div class="toolbar">
        <h2 class="panel-title" style="margin: 0">服务端模板</h2>
        <div class="grow" />
        <el-input
          v-model="templateName"
          size="small"
          placeholder="模板名称，如 default"
          style="width: 220px"
        />
        <el-checkbox v-model="activateOnSave" size="small">保存后激活</el-checkbox>
        <el-button size="small" :loading="templatesLoading" @click="loadTemplates">刷新</el-button>
      </div>
      <el-table
        v-loading="templatesLoading"
        :data="templates"
        row-key="id"
        size="small"
        max-height="360"
      >
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column prop="version" label="版本" width="80">
          <template #default="{ row }">v{{ row.version }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.active" type="success" size="small">激活</el-tag>
            <el-tag v-else type="info" size="small" effect="plain">历史</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" min-width="170" show-overflow-tooltip />
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="loadTemplate(row)">载入</el-button>
            <el-button link type="success" :disabled="row.active" @click="activateTemplate(row)">
              激活
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty
            :image-size="70"
            description="尚无服务端模板；可在下方编辑后点“保存到服务端”创建首个版本"
          />
        </template>
      </el-table>
    </div>

    <div class="panel">
      <div class="toolbar">
        <h2 class="panel-title" style="margin: 0">模板 JSON</h2>
        <div class="grow" />
        <el-tag v-if="jsonError" type="danger" size="small">JSON 无效</el-tag>
        <el-tag v-else type="success" size="small">JSON 有效</el-tag>
        <el-button size="small" @click="formatJson">格式化</el-button>
      </div>
      <el-alert
        v-if="jsonError"
        type="error"
        :title="jsonError"
        :closable="false"
        show-icon
        style="margin-bottom: 10px"
      />
      <el-input v-model="editor" class="code-input" type="textarea" :rows="22" spellcheck="false" />
      <div class="muted" style="margin-top: 10px; font-size: 12px">
        校验、保存与激活使用
        <span class="mono">/api/graph-templates/validate</span>、
        <span class="mono">POST /api/graph-templates</span> 与
        <span class="mono">/api/graph-templates/&lt;id&gt;/activate</span>。本地草稿仍保存在浏览器
        localStorage，不会自动写入服务端。
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { api, errorMessage } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'

interface FlowNode {
  id: string
  label: string
  sandbox?: boolean
}

interface GraphTemplate {
  id: number
  name: string
  version: number
  config: unknown
  active?: boolean
  created_at?: string
}

interface ValidationResult {
  ok: boolean
  errors: string[]
  nodes: string[]
}

const STORAGE_KEY = 'codesentry.orchestration.template.v1'

const defaultNodes: FlowNode[] = [
  { id: 'recon', label: 'Recon' },
  { id: 'scan', label: 'Scan' },
  { id: 'retrieval', label: 'Retrieval' },
  { id: 'triage', label: 'Triage' },
  { id: 'deploy', label: 'Deploy', sandbox: true },
  { id: 'poc_gen', label: 'PoC Gen' },
  { id: 'report', label: 'Report' },
]

function defaultTemplate(): Record<string, unknown> {
  return {
    template: 'default',
    version: 1,
    description: 'CodeSentry 默认 LangGraph 扫描链',
    nodes: defaultNodes.map((node) => ({
      id: node.id,
      label: node.label,
      agent: node.id,
      sandbox: node.sandbox === true,
    })),
    edges: defaultNodes.slice(0, -1).map((node, index) => ({
      from: node.id,
      to: defaultNodes[index + 1]?.id,
    })),
    interrupts: [{ kind: 'human_review', after: 'triage', optional: true }],
  }
}

function stringify(value: unknown): string {
  return JSON.stringify(value, null, 2)
}

const editor = ref(stringify(defaultTemplate()))
const templateName = ref('default')
const activateOnSave = ref(false)
const backendNote = ref('')
const backendOnline = ref(false)
const actionError = ref('')
const validation = ref<ValidationResult | null>(null)
const validating = ref(false)
const saving = ref(false)
const templatesLoading = ref(false)
const templates = ref<GraphTemplate[]>([])

const jsonError = computed(() => {
  try {
    const parsed = JSON.parse(editor.value)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return '模板必须是 JSON 对象'
    }
    return ''
  } catch (e) {
    return e instanceof Error ? e.message : String(e)
  }
})

function parseConfig(): Record<string, unknown> | null {
  actionError.value = ''
  try {
    const parsed = JSON.parse(editor.value)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      actionError.value = '模板必须是 JSON 对象'
      return null
    }
    return parsed as Record<string, unknown>
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : String(e)
    return null
  }
}

async function loadTemplates(): Promise<void> {
  templatesLoading.value = true
  try {
    const res = await api.get<{ templates?: GraphTemplate[] }>('/api/graph-templates')
    templates.value = Array.isArray(res?.templates) ? res.templates : []
    backendOnline.value = true
    backendNote.value = `已连接 /api/graph-templates（${templates.value.length} 个模板）`
  } catch (e) {
    backendOnline.value = false
    backendNote.value = `后端 /api/graph-templates 暂不可用：${errorMessage(e)}。仍可编辑和保存本地草稿。`
  } finally {
    templatesLoading.value = false
  }
}

async function validateTemplate(): Promise<void> {
  const config = parseConfig()
  if (!config) return
  validating.value = true
  validation.value = null
  try {
    validation.value = await api.post<ValidationResult>('/api/graph-templates/validate', {
      name: templateName.value.trim() || 'draft',
      config,
    })
    if (validation.value.ok) ElMessage.success('模板校验通过')
  } catch (e) {
    actionError.value = `校验失败：${errorMessage(e)}`
  } finally {
    validating.value = false
  }
}

async function saveTemplate(): Promise<void> {
  const config = parseConfig()
  if (!config) return
  const name = templateName.value.trim()
  if (!name) {
    actionError.value = '请填写模板名称'
    return
  }
  saving.value = true
  try {
    const res = await api.post<{ id: number; name: string; version: number }>(
      '/api/graph-templates',
      { name, config, activate: activateOnSave.value },
    )
    ElMessage.success(`模板 ${res.name} v${res.version} 已保存`)
    backendNote.value = `模板 ${res.name} v${res.version} 已保存${
      activateOnSave.value ? '并激活' : ''
    }`
    await loadTemplates()
  } catch (e) {
    actionError.value = `保存失败：${errorMessage(e)}`
  } finally {
    saving.value = false
  }
}

async function activateTemplate(row: GraphTemplate): Promise<void> {
  actionError.value = ''
  try {
    await api.post(`/api/graph-templates/${row.id}/activate`)
    ElMessage.success(`模板 ${row.name} v${row.version} 已激活`)
    await loadTemplates()
  } catch (e) {
    actionError.value = `激活失败：${errorMessage(e)}`
  }
}

function loadTemplate(row: GraphTemplate): void {
  try {
    const config = typeof row.config === 'string' ? JSON.parse(row.config) : row.config
    editor.value = stringify(config)
    templateName.value = row.name
    validation.value = null
    actionError.value = ''
    ElMessage.success(`已载入 ${row.name} v${row.version}`)
  } catch (e) {
    actionError.value = `模板内容无法解析：${errorMessage(e)}`
  }
}

function resetTemplate(): void {
  editor.value = stringify(defaultTemplate())
  templateName.value = 'default'
  validation.value = null
  actionError.value = ''
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // localStorage 不可用时忽略
  }
  ElMessage.success('已恢复默认模板')
}

function formatJson(): void {
  if (jsonError.value) {
    ElMessage.error(jsonError.value)
    return
  }
  editor.value = stringify(JSON.parse(editor.value))
  ElMessage.success('已格式化')
}

function saveDraft(): void {
  if (jsonError.value) {
    ElMessage.error(jsonError.value)
    return
  }
  try {
    localStorage.setItem(STORAGE_KEY, editor.value)
    ElMessage.success('草稿已保存到浏览器本地（未写入服务端）')
  } catch {
    ElMessage.error('localStorage 不可用，无法保存草稿')
  }
}

onMounted(() => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) editor.value = stored
  } catch {
    // ignore
  }
  void loadTemplates()
})
</script>

<style scoped>
.flow {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.flow-node {
  border: 1px solid var(--cs-border);
  background: var(--cs-panel-soft);
  border-radius: 10px;
  padding: 10px 14px;
  min-width: 96px;
}

.flow-node.sandbox {
  border-color: #93c5fd;
  background: #eff6ff;
}

.flow-node-label {
  font-weight: 650;
  margin-bottom: 2px;
}

.flow-arrow {
  color: #94a3b8;
  font-size: 18px;
}

.error-list {
  margin: 6px 0 0;
  padding-left: 18px;
}
</style>
