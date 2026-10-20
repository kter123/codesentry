<template>
  <div>
    <page-header title="Skills 管理" subtitle="SKILL.md 上传、版本、按 Agent 分配与注入预览">
      <template #actions>
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
        <el-button type="primary" @click="openUpload">上传 SKILL.md</el-button>
      </template>
    </page-header>

    <error-alert :message="error" @retry="load" />

    <div class="panel">
      <el-table v-loading="loading" :data="skills" row-key="name">
        <el-table-column label="名称" min-width="160">
          <template #default="{ row }">
            <div><strong>{{ row.name }}</strong></div>
            <div class="mono muted">v{{ row.versions || 0 }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="240" show-overflow-tooltip />
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.enabled === false ? 'info' : 'success'">
              {{ row.enabled === false ? '停用' : '启用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="已分配 Agent" min-width="210">
          <template #default="{ row }">
            <div v-if="enabledAgents(row).length" class="inline-tags">
              <el-tag v-for="agent in enabledAgents(row)" :key="agent" size="small" effect="plain">
                {{ agent }}
              </el-tag>
            </div>
            <span v-else class="muted">未分配</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openAssign(row)">分配</el-button>
            <el-button link @click="openPreview(row)">注入预览</el-button>
            <el-button link @click="openUsage(row)">使用记录</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :image-size="80" description="还没有 Skill。上传 SKILL.md 以创建第一个 Skill。">
            <el-button type="primary" @click="openUpload">上传 SKILL.md</el-button>
          </el-empty>
        </template>
      </el-table>
    </div>

    <el-dialog v-model="uploadVisible" title="上传 SKILL.md" width="720px" destroy-on-close>
      <el-alert v-if="uploadError" type="error" :title="uploadError" :closable="false" show-icon style="margin-bottom: 12px" />
      <div class="toolbar">
        <el-upload :auto-upload="false" :show-file-list="false" accept=".md,.markdown,text/markdown" :on-change="readFile">
          <el-button>选择本地 SKILL.md</el-button>
        </el-upload>
        <span class="muted">frontmatter 需包含 name 与 description，正文使用 Markdown。</span>
      </div>
      <el-input
        v-model="skillText"
        class="code-input"
        type="textarea"
        :rows="16"
        placeholder="---&#10;name: sql-injection-review&#10;description: 检查 SQL 注入证据链&#10;---&#10;&#10;正文…"
      />
      <template #footer>
        <el-button @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" :disabled="!skillText.trim()" @click="upload">
          上传并创建版本
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="assignVisible" :title="`分配 Skill · ${activeSkill?.name || ''}`" width="500px">
      <el-alert v-if="assignError" type="error" :title="assignError" :closable="false" show-icon style="margin-bottom: 12px" />
      <el-form label-position="top">
        <el-form-item label="Agent">
          <el-select v-model="assignForm.agent" style="width: 100%">
            <el-option v-for="agent in AGENTS" :key="agent" :label="agent" :value="agent" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用分配">
          <el-switch v-model="assignForm.enabled" />
        </el-form-item>
        <el-form-item label="版本固定（留空使用最新）">
          <el-input-number v-model="assignForm.version_pin" :min="1" :step="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="优先级（值越小越靠前）">
          <el-input-number v-model="assignForm.priority" :min="0" :max="1000" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="assignVisible = false">取消</el-button>
        <el-button type="primary" :loading="assigning" @click="saveAssign">保存分配</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="previewVisible" :title="`注入预览 · ${activeSkill?.name || ''}`" width="780px">
      <div class="toolbar">
        <el-select v-model="previewAgents" multiple collapse-tags placeholder="选择 Agent" style="min-width: 300px">
          <el-option v-for="agent in AGENTS" :key="agent" :label="agent" :value="agent" />
        </el-select>
        <el-button type="primary" :loading="previewLoading" @click="runPreview">生成预览</el-button>
      </div>
      <el-alert v-if="previewError" type="error" :title="previewError" :closable="false" show-icon />
      <template v-if="previewResult">
        <el-card v-for="(item, agent) in previewResult" :key="agent" shadow="never" style="margin-bottom: 12px">
          <template #header>
            <strong>{{ agent }}</strong>
            <span class="muted mono" style="margin-left: 10px">
              prompt v{{ item.prompt_version ?? 'seed' }} · {{ item.skills_tokens_est ?? 0 }} skill tokens
            </span>
          </template>
          <div class="muted" style="margin-bottom: 6px">Prompt 预览</div>
          <pre class="pre-block light" style="max-height: 140px">{{ item.prompt_preview || '—' }}</pre>
          <div class="muted" style="margin: 8px 0 6px">Skills 注入块</div>
          <pre class="pre-block" style="max-height: 180px">{{ item.skills_block || '（无）' }}</pre>
          <el-alert
            v-for="(warning, index) in item.warnings || []"
            :key="index"
            type="warning"
            :title="warning"
            :closable="false"
            show-icon
            style="margin-top: 8px"
          />
        </el-card>
        <el-empty v-if="!Object.keys(previewResult).length" :image-size="60" description="没有预览结果" />
      </template>
    </el-dialog>

    <el-dialog v-model="usageVisible" :title="`使用记录 · ${activeSkill?.name || ''}`" width="680px">
      <el-alert v-if="usageError" type="error" :title="usageError" :closable="false" show-icon style="margin-bottom: 12px" />
      <el-table v-loading="usageLoading" :data="usageRows" size="small">
        <el-table-column prop="scan_id" label="扫描 ID" width="100" />
        <el-table-column prop="status" label="状态" width="120">
          <template #default="{ row }"><status-tag :status="row.status" /></template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" min-width="180" />
        <template #empty>
          <el-empty :image-size="60" description="没有使用该 Skill 的扫描快照记录" />
        </template>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { UploadFile } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { api, errorMessage } from '@/api/client'
import type { SkillRow } from '@/api/types'
import ErrorAlert from '@/components/ErrorAlert.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'

interface AgentPreview {
  prompt_version?: number | null
  prompt_preview?: string
  skills_block?: string
  skills_tokens_est?: number
  prompt_tokens_est?: number
  warnings?: string[]
}

interface SkillUsageRow {
  scan_id: number
  created_at?: string
  status?: string
}

const AGENTS = ['recon', 'scan', 'retrieval', 'triage', 'poc_gen', 'report']

const loading = ref(false)
const error = ref('')
const skills = ref<SkillRow[]>([])
const activeSkill = ref<SkillRow | null>(null)

const uploadVisible = ref(false)
const uploading = ref(false)
const uploadError = ref('')
const skillText = ref('')

const assignVisible = ref(false)
const assigning = ref(false)
const assignError = ref('')
const assignForm = reactive<{
  agent: string
  enabled: boolean
  version_pin: number | undefined
  priority: number
}>({ agent: 'triage', enabled: true, version_pin: undefined, priority: 100 })

const previewVisible = ref(false)
const previewLoading = ref(false)
const previewError = ref('')
const previewAgents = ref<string[]>(['recon', 'scan', 'triage'])
const previewResult = ref<Record<string, AgentPreview> | null>(null)

const usageVisible = ref(false)
const usageLoading = ref(false)
const usageError = ref('')
const usageRows = ref<SkillUsageRow[]>([])

function enabledAgents(row: SkillRow): string[] {
  const assigned = row.assigned || {}
  const names = Object.entries(assigned)
    .filter(([, enabled]) => enabled)
    .map(([agent]) => agent)
  if (names.length) return names
  return (row.assignments || []).filter((item) => item.enabled).map((item) => item.agent)
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const res = await api.get<{ skills: SkillRow[] }>('/api/skills')
    skills.value = res?.skills ?? []
  } catch (e) {
    error.value = `加载 Skills 失败：${errorMessage(e)}`
  } finally {
    loading.value = false
  }
}

function openUpload(): void {
  skillText.value = ''
  uploadError.value = ''
  uploadVisible.value = true
}

function readFile(file: UploadFile): void {
  const raw = file.raw
  if (!raw) return
  const reader = new FileReader()
  reader.onload = () => {
    skillText.value = String(reader.result || '')
  }
  reader.onerror = () => {
    uploadError.value = '读取文件失败'
  }
  reader.readAsText(raw)
}

function deriveName(text: string): string {
  const match = text.match(/^---\s*[\r\n]+([\s\S]*?)[\r\n]+---/)
  if (match) {
    const nameLine = match[1]
      .split(/\r?\n/)
      .find((line) => line.trim().startsWith('name:'))
    if (nameLine) return nameLine.split(':', 2)[1]?.trim() || 'skill'
  }
  return 'skill'
}

async function upload(): Promise<void> {
  uploadError.value = ''
  if (!skillText.value.trim()) {
    uploadError.value = 'SKILL.md 内容为空'
    return
  }
  uploading.value = true
  try {
    const res = await api.post<{ name: string; version: number }>('/api/skills/upload', {
      name: deriveName(skillText.value),
      body: skillText.value,
    })
    ElMessage.success(`Skill ${res.name} v${res.version} 已创建`)
    uploadVisible.value = false
    await load()
  } catch (e) {
    uploadError.value = errorMessage(e)
  } finally {
    uploading.value = false
  }
}

function openAssign(row: SkillRow): void {
  activeSkill.value = row
  assignError.value = ''
  Object.assign(assignForm, { agent: 'triage', enabled: true, version_pin: undefined, priority: 100 })
  assignVisible.value = true
}

async function saveAssign(): Promise<void> {
  if (!activeSkill.value) return
  assignError.value = ''
  assigning.value = true
  try {
    await api.post(`/api/skills/${encodeURIComponent(activeSkill.value.name)}/assign`, {
      agent: assignForm.agent,
      enabled: assignForm.enabled,
      version_pin: assignForm.version_pin ?? null,
      priority: assignForm.priority,
    })
    ElMessage.success('分配已保存')
    assignVisible.value = false
    await load()
  } catch (e) {
    assignError.value = errorMessage(e)
  } finally {
    assigning.value = false
  }
}

function openPreview(row: SkillRow): void {
  activeSkill.value = row
  previewResult.value = null
  previewError.value = ''
  previewVisible.value = true
}

async function runPreview(): Promise<void> {
  if (!activeSkill.value) return
  previewLoading.value = true
  previewError.value = ''
  try {
    const res = await api.post<{ skill: string; agents: Record<string, AgentPreview> }>(
      `/api/skills/${encodeURIComponent(activeSkill.value.name)}/preview`,
      { agents: previewAgents.value },
    )
    previewResult.value = res?.agents ?? {}
  } catch (e) {
    previewError.value = errorMessage(e)
  } finally {
    previewLoading.value = false
  }
}

async function openUsage(row: SkillRow): Promise<void> {
  activeSkill.value = row
  usageRows.value = []
  usageError.value = ''
  usageVisible.value = true
  usageLoading.value = true
  try {
    const res = await api.get<{ skill: string; scans: SkillUsageRow[] }>(
      `/api/skills/${encodeURIComponent(row.name)}/usage`,
    )
    usageRows.value = res?.scans ?? []
  } catch (e) {
    usageError.value = errorMessage(e)
  } finally {
    usageLoading.value = false
  }
}

onMounted(load)
</script>
