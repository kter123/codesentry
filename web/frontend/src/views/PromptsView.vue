<template>
  <div>
    <page-header title="Prompt 管理" subtitle="版本、激活、回滚、Diff 与静态 lint">
      <template #actions>
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
        <el-button type="primary" @click="openCreate()">新建版本</el-button>
      </template>
    </page-header>

    <error-alert :message="error" @retry="load" />

    <el-row :gutter="18">
      <el-col :xs="24" :lg="8">
        <div v-loading="loading" class="panel">
          <h2 class="panel-title">Prompt 列表</h2>
          <el-table
            :data="prompts"
            size="small"
            highlight-current-row
            row-key="name"
            @row-click="selectPrompt"
          >
            <el-table-column prop="name" label="名称" min-width="100" />
            <el-table-column label="激活" width="80">
              <template #default="{ row }">
                <el-tag v-if="row.active_version" size="small" type="success">
                  v{{ row.active_version }}
                </el-tag>
                <span v-else class="muted">seed</span>
              </template>
            </el-table-column>
            <el-table-column label="最新" width="70">
              <template #default="{ row }">v{{ row.latest_version ?? '—' }}</template>
            </el-table-column>
            <template #empty>
              <el-empty
                :image-size="70"
                description="暂无 Prompt 版本记录（DB 不可用或尚未初始化）"
              >
                <el-button size="small" @click="openCreate()">创建第一个版本</el-button>
              </el-empty>
            </template>
          </el-table>
        </div>

        <div class="panel">
          <h2 class="panel-title">
            版本历史
            <span class="panel-subtitle">{{ selectedName || '未选择' }}</span>
          </h2>
          <el-table
            v-if="versions.length"
            :data="versions"
            size="small"
            highlight-current-row
            row-key="version"
            @row-click="loadVersion"
          >
            <el-table-column label="版本" width="80">
              <template #default="{ row }">
                v{{ row.version }}
                <el-tag v-if="row.active" size="small" type="success" style="margin-left: 4px">active</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="SHA" min-width="100">
              <template #default="{ row }">
                <span class="mono">{{ (row.body_sha256 || '').slice(0, 10) || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="创建时间" min-width="130" show-overflow-tooltip>
              <template #default="{ row }">{{ row.created || row.created_at || '—' }}</template>
            </el-table-column>
            <template #empty>
              <el-empty :image-size="50" description="没有版本记录" />
            </template>
          </el-table>
          <el-empty v-else :image-size="56" description="选择左侧 Prompt 查看版本" />
          <div v-if="versions.length" class="toolbar" style="margin-top: 10px">
            <el-button size="small" :disabled="!selectedVersion" @click="activateVersion">激活</el-button>
            <el-button size="small" :disabled="!selectedVersion" @click="rollbackVersion">回滚到此版本</el-button>
            <el-button size="small" @click="openDiff">Diff</el-button>
          </div>
        </div>
      </el-col>

      <el-col :xs="24" :lg="16">
        <div class="panel">
          <div class="toolbar">
            <h2 class="panel-title" style="margin: 0">
              Prompt 编辑器
              <span class="panel-subtitle">
                {{ selectedName || '从左侧选择，或直接新建' }}
                <template v-if="selectedVersion"> · v{{ selectedVersion.version }}</template>
              </span>
            </h2>
            <div class="grow" />
            <el-button size="small" :loading="linting" :disabled="!editorBody.trim()" @click="lint">
              Lint
            </el-button>
            <el-button size="small" @click="openCreate(selectedName, editorBody)">另存为新版本</el-button>
          </div>

          <el-alert
            v-if="!versions.length && selectedName"
            type="info"
            :closable="false"
            show-icon
            :title="`${selectedName} 尚无数据库版本，编辑器内容可能来自种子 Prompt。保存后会创建 v1。`"
            style="margin-bottom: 10px"
          />
          <el-input
            v-model="editorBody"
            class="code-input"
            type="textarea"
            :rows="20"
            placeholder="在此编辑 Prompt 正文；POST /api/prompts 会自动创建并激活新版本。"
          />

          <div v-if="lintResult" class="lint-result">
            <el-alert
              :type="lintResult.ok ? 'success' : 'error'"
              :title="lintResult.ok ? 'Lint 通过' : 'Lint 未通过'"
              :closable="false"
              show-icon
            />
            <div v-if="lintResult.errors?.length" style="margin-top: 8px">
              <el-tag v-for="(item, index) in lintResult.errors" :key="index" type="danger" effect="plain" style="margin: 0 6px 6px 0">
                {{ item }}
              </el-tag>
            </div>
            <div v-if="lintResult.warnings?.length" style="margin-top: 8px">
              <el-tag v-for="(item, index) in lintResult.warnings" :key="index" type="warning" effect="plain" style="margin: 0 6px 6px 0">
                {{ item }}
              </el-tag>
            </div>
          </div>

          <div class="toolbar" style="margin-top: 14px; margin-bottom: 0">
            <el-button
              type="primary"
              :disabled="!selectedName || !editorBody.trim()"
              @click="saveEditorVersion"
            >
              保存为 {{ selectedName || '新' }} 的新版本
            </el-button>
            <span class="muted">{{ editorBody.length.toLocaleString() }} 字符 · 约 {{ Math.ceil(editorBody.length / 4).toLocaleString() }} tokens</span>
          </div>
        </div>
      </el-col>
    </el-row>

    <el-dialog v-model="createVisible" title="新建 Prompt 版本" width="720px" destroy-on-close>
      <el-alert v-if="createError" type="error" :title="createError" :closable="false" show-icon style="margin-bottom: 12px" />
      <el-form label-position="top">
        <el-form-item label="Prompt 名称（Agent）">
          <el-select v-model="createName" filterable allow-create default-first-option style="width: 100%">
            <el-option v-for="name in agentOptions" :key="name" :label="name" :value="name" />
          </el-select>
        </el-form-item>
        <el-form-item label="正文">
          <el-input v-model="createBody" class="code-input" type="textarea" :rows="16" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createVersion">创建并激活</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="diffVisible" title="版本 Diff" width="800px">
      <div class="toolbar">
        <el-select v-model="diffA" placeholder="旧版本" style="width: 150px">
          <el-option v-for="v in versions" :key="v.version" :label="`v${v.version}`" :value="v.version" />
        </el-select>
        <span>→</span>
        <el-select v-model="diffB" placeholder="新版本" style="width: 150px">
          <el-option v-for="v in versions" :key="v.version" :label="`v${v.version}`" :value="v.version" />
        </el-select>
        <el-button type="primary" :loading="diffLoading" @click="loadDiff">生成 Diff</el-button>
      </div>
      <el-alert v-if="diffError" type="error" :title="diffError" :closable="false" show-icon />
      <pre v-if="diffText" class="pre-block diff-block"><span
        v-for="(line, index) in diffLines"
        :key="index"
        :class="line.cls"
      >{{ line.text + '\n' }}</span></pre>
      <el-empty v-else :image-size="60" description="选择两个版本后生成 unified diff" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { api, errorMessage } from '@/api/client'
import type { PromptSummary, PromptVersion } from '@/api/types'
import ErrorAlert from '@/components/ErrorAlert.vue'
import PageHeader from '@/components/PageHeader.vue'

interface LintResult {
  ok: boolean
  errors?: string[]
  warnings?: string[]
}

const AGENT_OPTIONS = ['recon', 'scan', 'retrieval', 'triage', 'poc_gen', 'report']

const route = useRoute()
const loading = ref(false)
const error = ref('')
const prompts = ref<PromptSummary[]>([])
const selectedName = ref('')
const versions = ref<PromptVersion[]>([])
const selectedVersion = ref<PromptVersion | null>(null)
const editorBody = ref('')
const linting = ref(false)
const lintResult = ref<LintResult | null>(null)

const createVisible = ref(false)
const createName = ref('')
const createBody = ref('')
const createError = ref('')
const creating = ref(false)

const diffVisible = ref(false)
const diffA = ref<number | undefined>()
const diffB = ref<number | undefined>()
const diffLoading = ref(false)
const diffError = ref('')
const diffText = ref('')

const agentOptions = computed(() => {
  const names = new Set<string>([...AGENT_OPTIONS, ...prompts.value.map((p) => p.name)])
  return [...names]
})

const diffLines = computed(() =>
  diffText.value.split('\n').map((line) => {
    let cls = ''
    if ((line.startsWith('+') && !line.startsWith('+++')) || line.startsWith('@@')) {
      cls = line.startsWith('@@') ? 'diff-meta' : 'diff-add'
    } else if (line.startsWith('-') && !line.startsWith('---')) {
      cls = 'diff-del'
    } else if (line.startsWith('---') || line.startsWith('+++')) {
      cls = 'diff-meta'
    }
    return { text: line, cls }
  }),
)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const res = await api.get<{ prompts: PromptSummary[] }>('/api/prompts')
    prompts.value = res?.prompts ?? []
    const requested = typeof route.query.name === 'string' ? route.query.name : ''
    const target =
      requested ||
      selectedName.value ||
      prompts.value.find((p) => p.active_version)?.name ||
      prompts.value[0]?.name ||
      ''
    if (target) await selectPrompt({ name: target })
    else {
      selectedName.value = ''
      versions.value = []
      selectedVersion.value = null
      editorBody.value = ''
    }
  } catch (e) {
    error.value = `加载 Prompts 失败：${errorMessage(e)}`
  } finally {
    loading.value = false
  }
}

async function selectPrompt(row: PromptSummary | { name: string }): Promise<void> {
  const name = row.name
  if (!name) return
  selectedName.value = name
  selectedVersion.value = null
  lintResult.value = null
  try {
    const res = await api.get<{ name: string; versions: PromptVersion[] }>(
      `/api/prompts/${encodeURIComponent(name)}/versions`,
    )
    versions.value = res?.versions ?? []
  } catch (e) {
    versions.value = []
    const status = (e as { status?: number }).status
    if (status !== 404) error.value = `加载版本失败：${errorMessage(e)}`
  }

  const active = versions.value.find((v) => v.active)
  const fallback = active ?? versions.value[0]
  if (fallback) {
    selectedVersion.value = fallback
    editorBody.value = fallback.body ?? ''
    diffA.value = versions.value[versions.value.length - 1]?.version
    diffB.value = versions.value[0]?.version
  } else {
    editorBody.value = ''
  }
}

function loadVersion(row: PromptVersion): void {
  selectedVersion.value = row
  editorBody.value = row.body ?? ''
}

async function createVersion(): Promise<void> {
  createError.value = ''
  if (!createName.value.trim()) {
    createError.value = '请填写 Prompt 名称'
    return
  }
  if (!createBody.value.trim()) {
    createError.value = 'Prompt 正文不能为空'
    return
  }
  creating.value = true
  try {
    const res = await api.post<{ name: string; version: number }>('/api/prompts', {
      name: createName.value.trim(),
      body: createBody.value,
    })
    ElMessage.success(`已创建 ${res.name} v${res.version} 并激活`)
    createVisible.value = false
    selectedName.value = res.name
    await load()
  } catch (e) {
    createError.value = errorMessage(e)
  } finally {
    creating.value = false
  }
}

function openCreate(name = '', body = ''): void {
  createName.value = name || selectedName.value || ''
  createBody.value = body || editorBody.value || ''
  createError.value = ''
  createVisible.value = true
}

async function saveEditorVersion(): Promise<void> {
  if (!selectedName.value) return
  try {
    await ElMessageBox.confirm(
      `将 ${selectedName.value} 的当前编辑器内容保存为新版本并激活，是否继续？`,
      '保存 Prompt 版本',
      { type: 'info', confirmButtonText: '保存', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  const name = selectedName.value
  const body = editorBody.value
  createName.value = name
  createBody.value = body
  await createVersion()
}

async function activateVersion(): Promise<void> {
  if (!selectedName.value || !selectedVersion.value) return
  try {
    await api.post(
      `/api/prompts/${encodeURIComponent(selectedName.value)}/activate`,
      { version: selectedVersion.value.version },
    )
    ElMessage.success(`已激活 v${selectedVersion.value.version}`)
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function rollbackVersion(): Promise<void> {
  if (!selectedName.value || !selectedVersion.value) return
  try {
    await ElMessageBox.confirm(
      `将复制 v${selectedVersion.value.version} 的正文创建新版本并激活，是否继续？`,
      '回滚 Prompt',
      { type: 'warning', confirmButtonText: '回滚', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await api.post(`/api/prompts/${encodeURIComponent(selectedName.value)}/rollback`, {
      version: selectedVersion.value.version,
    })
    ElMessage.success('回滚完成')
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function lint(): Promise<void> {
  linting.value = true
  lintResult.value = null
  try {
    lintResult.value = await api.post<LintResult>('/api/prompts/lint', { body: editorBody.value })
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    linting.value = false
  }
}

function openDiff(): void {
  if (!versions.value.length) return
  diffA.value = diffA.value ?? versions.value[versions.value.length - 1]?.version
  diffB.value = diffB.value ?? versions.value[0]?.version
  diffText.value = ''
  diffError.value = ''
  diffVisible.value = true
}

async function loadDiff(): Promise<void> {
  if (!selectedName.value || !diffA.value || !diffB.value) return
  diffLoading.value = true
  diffError.value = ''
  try {
    const res = await api.get<{ name: string; diff: string }>(
      `/api/prompts/${encodeURIComponent(selectedName.value)}/diff`,
      { a: diffA.value, b: diffB.value },
    )
    diffText.value = res?.diff ?? ''
  } catch (e) {
    diffError.value = errorMessage(e)
    diffText.value = ''
  } finally {
    diffLoading.value = false
  }
}

watch(
  () => route.query.name,
  (name) => {
    if (typeof name === 'string' && name && name !== selectedName.value) {
      void selectPrompt({ name })
    }
  },
)

onMounted(load)
</script>

<style scoped>
.lint-result {
  margin-top: 12px;
}
</style>
