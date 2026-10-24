<template>
  <div>
    <page-header title="知识库" subtitle="切块预览、来源重建与全文检索">
      <template #actions>
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
        <el-button type="primary" :loading="rebuilding" @click="rebuildAll">重建全部索引</el-button>
      </template>
    </page-header>

    <error-alert :message="error" @retry="load" />

    <el-row :gutter="16">
      <el-col :xs="12" :sm="6">
        <div class="panel stat">
          <div class="stat-label">Chunks</div>
          <div class="stat-value">{{ stats.chunks ?? 0 }}</div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="panel stat">
          <div class="stat-label">来源</div>
          <div class="stat-value">{{ stats.sources ?? 0 }}</div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="14">
        <div class="panel">
          <h2 class="panel-title">来源</h2>
          <el-table :data="stats.by_source || []" size="small">
            <el-table-column prop="source" label="来源" min-width="220" show-overflow-tooltip />
            <el-table-column prop="chunks" label="Chunks" width="90" />
            <el-table-column label="操作" width="220">
              <template #default="{ row }">
                <el-button link type="primary" @click="openChunks(row.source)">预览</el-button>
                <el-button link @click="rebuild(row.source)">重建</el-button>
                <el-button link type="danger" @click="removeSource(row.source)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty><el-empty :image-size="50" description="知识库为空" /></template>
          </el-table>
        </div>

        <div class="panel">
          <h2 class="panel-title">检索</h2>
          <div class="toolbar">
            <el-input v-model="query" placeholder="关键词，例如 SSRF 白名单" clearable style="max-width: 320px" @keyup.enter="search" />
            <el-button :loading="searching" @click="search">检索</el-button>
          </div>
          <el-table :data="results" size="small" max-height="320">
            <el-table-column prop="source" label="来源" width="150" show-overflow-tooltip />
            <el-table-column prop="title" label="标题" width="150" show-overflow-tooltip />
            <el-table-column prop="content" label="内容" min-width="260" show-overflow-tooltip />
            <el-table-column prop="score" label="分数" width="80" />
            <template #empty><el-empty :image-size="46" description="输入关键词检索" /></template>
          </el-table>
        </div>
      </el-col>

      <el-col :xs="24" :lg="10">
        <div class="panel">
          <h2 class="panel-title">导入文本</h2>
          <el-form label-position="top">
            <el-form-item label="来源（source）">
              <el-input v-model="form.source" placeholder="例如 owasp-notes" />
            </el-form-item>
            <el-form-item label="标题">
              <el-input v-model="form.title" placeholder="SSRF 防护要点" />
            </el-form-item>
            <el-form-item label="正文（空行分段）">
              <el-input v-model="form.content" class="code-input" type="textarea" :rows="10" />
            </el-form-item>
          </el-form>
          <div class="toolbar">
            <el-button :loading="previewing" @click="preview">切块预览</el-button>
            <el-button type="primary" :loading="importing" @click="importText">导入</el-button>
          </div>
        </div>
      </el-col>
    </el-row>

    <el-dialog v-model="chunksVisible" :title="`切块预览 · ${chunkSource}`" width="860px">
      <el-table :data="chunks" size="small" max-height="480">
        <el-table-column prop="id" label="#" width="70" />
        <el-table-column prop="title" label="标题" width="160" show-overflow-tooltip />
        <el-table-column prop="embedding_dims" label="向量维度" width="90" />
        <el-table-column prop="content" label="内容" min-width="360" show-overflow-tooltip />
      </el-table>
    </el-dialog>

    <el-dialog v-model="previewVisible" title="切块预览（未入库）" width="760px">
      <el-table :data="previewChunks" size="small" max-height="420">
        <el-table-column prop="index" label="#" width="60" />
        <el-table-column prop="chars" label="字符" width="80" />
        <el-table-column prop="content" label="内容" min-width="420" show-overflow-tooltip />
      </el-table>
      <template #footer>
        <el-button @click="previewVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { api, errorMessage } from '@/api/client'
import ErrorAlert from '@/components/ErrorAlert.vue'
import PageHeader from '@/components/PageHeader.vue'

interface KbStats {
  chunks?: number
  sources?: number
  by_source?: Array<{ source: string; chunks: number }>
}

const loading = ref(false)
const rebuilding = ref(false)
const searching = ref(false)
const importing = ref(false)
const previewing = ref(false)
const error = ref('')
const stats = ref<KbStats>({})
const query = ref('')
const results = ref<Array<Record<string, unknown>>>([])
const chunks = ref<Array<Record<string, unknown>>>([])
const chunksVisible = ref(false)
const chunkSource = ref('')
const previewVisible = ref(false)
const previewChunks = ref<Array<Record<string, unknown>>>([])
const form = reactive({ source: '', title: '', content: '' })

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    stats.value = await api.get<KbStats>('/api/kb/stats')
  } catch (e) {
    error.value = `加载知识库失败：${errorMessage(e)}`
  } finally {
    loading.value = false
  }
}

async function search(): Promise<void> {
  if (!query.value.trim()) return
  searching.value = true
  try {
    const res = await api.post<{ rows?: Array<Record<string, unknown>> }>('/api/kb/search', {
      query: query.value,
      top_k: 10,
    })
    results.value = res.rows || []
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    searching.value = false
  }
}

async function openChunks(source: string): Promise<void> {
  chunkSource.value = source
  try {
    const res = await api.get<{ chunks?: Array<Record<string, unknown>> }>('/api/kb/chunks', {
      source,
      limit: 100,
    })
    chunks.value = res.chunks || []
    chunksVisible.value = true
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function rebuild(source: string): Promise<void> {
  try {
    const res = await api.post<{ rebuilt?: number; degraded?: boolean }>('/api/kb/rebuild', { source })
    ElMessage.success(`重建完成：${res.rebuilt ?? 0} 个 chunk${res.degraded ? '（embedding 不可用，已降级）' : ''}`)
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function rebuildAll(): Promise<void> {
  rebuilding.value = true
  try {
    const res = await api.post<{ rebuilt?: number; degraded?: boolean }>('/api/kb/rebuild', { source: '' })
    ElMessage.success(`全量重建：${res.rebuilt ?? 0} 个 chunk${res.degraded ? '（已降级）' : ''}`)
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    rebuilding.value = false
  }
}

async function removeSource(source: string): Promise<void> {
  try {
    await ElMessageBox.confirm(`删除来源「${source}」的全部 chunk？`, '删除知识来源', { type: 'warning' })
  } catch {
    return
  }
  try {
    await api.del('/api/kb/source', { query: { source } })
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function preview(): Promise<void> {
  if (!form.content.trim()) {
    ElMessage.warning('请先填写正文')
    return
  }
  previewing.value = true
  try {
    const res = await api.post<{ chunks?: Array<Record<string, unknown>> }>('/api/kb/preview', {
      content: form.content,
      size: 800,
    })
    previewChunks.value = res.chunks || []
    previewVisible.value = true
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    previewing.value = false
  }
}

async function importText(): Promise<void> {
  if (!form.source.trim() || !form.content.trim()) {
    ElMessage.warning('来源与正文必填')
    return
  }
  importing.value = true
  try {
    await api.post('/api/kb/import', {
      source: form.source.trim(),
      title: form.title.trim() || form.source.trim(),
      content: form.content,
    })
    ElMessage.success('导入完成')
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    importing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.stat-label {
  color: #64748b;
  font-size: 13px;
}
.stat-value {
  font-size: 26px;
  font-weight: 600;
  margin-top: 6px;
}
</style>
