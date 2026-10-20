<template>
  <div>
    <page-header
      title="复核队列"
      subtitle="对中断在 human_review 的扫描逐条批准、驳回或调整置信度"
    >
      <template #actions>
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
      </template>
    </page-header>

    <el-alert
      type="info"
      show-icon
      :closable="false"
      title="队列仅列出存在 interrupted 节点的扫描；待复核 findings 优先读取 /api/scans/{id}/findings，失败时从扫描图接口聚合。"
      style="margin-bottom: 14px"
    />

    <div class="panel">
      <error-alert :message="error" @retry="load" />
      <el-table v-loading="loading" :data="queue" row-key="id">
        <el-table-column prop="id" label="扫描 ID" width="90" />
        <el-table-column prop="repo_path" label="仓库" min-width="300" show-overflow-tooltip />
        <el-table-column label="状态" width="120">
          <template #default="{ row }"><status-tag :status="row.status" /></template>
        </el-table-column>
        <el-table-column prop="created" label="创建时间" min-width="180" />
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openReview(row)">开始复核</el-button>
            <el-button link @click="$router.push(`/scans/${row.id}`)">查看详情</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty
            :image-size="80"
            description="没有等待复核的扫描（扫描尚未中断或已全部复核）"
          />
        </template>
      </el-table>
    </div>

    <el-drawer v-model="drawer" :title="reviewScan ? `复核扫描 #${reviewScan.id}` : '复核'" size="70%" destroy-on-close>
      <div v-loading="reviewLoading">
        <error-alert :message="reviewError" :retryable="false" />
        <div v-if="reviewScan" class="toolbar">
          <span class="mono muted">{{ reviewScan.repo_path }}</span>
          <div class="grow" />
          <el-button size="small" @click="bulk('approve')">全部通过</el-button>
          <el-button size="small" type="danger" plain @click="bulk('reject')">全部驳回</el-button>
        </div>

        <el-alert
          v-if="reviewNote"
          type="warning"
          :title="reviewNote"
          show-icon
          :closable="false"
          style="margin-bottom: 12px"
        />

        <el-table v-if="pending.length" :data="pending" size="small" row-key="id" max-height="440">
          <el-table-column prop="rule_id" label="规则" min-width="170" show-overflow-tooltip />
          <el-table-column prop="severity" label="严重度" width="95">
            <template #default="{ row }"><status-tag :status="row.severity" /></template>
          </el-table-column>
          <el-table-column label="位置" min-width="190" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono">{{ row.file_rel || row.file || '—' }}:{{ row.line ?? '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="message" label="描述" min-width="200" show-overflow-tooltip />
          <el-table-column label="决策" width="150">
            <template #default="{ row }">
              <el-select v-model="row._verdict" size="small">
                <el-option label="通过" value="approve" />
                <el-option label="驳回" value="reject" />
                <el-option label="调整" value="adjust" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="置信度" width="145">
            <template #default="{ row }">
              <el-input-number
                v-model="row._confidence"
                size="small"
                :min="0"
                :max="1"
                :step="0.05"
                :precision="2"
                :disabled="row._verdict === 'reject'"
                controls-position="right"
                style="width: 120px"
              />
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="没有待复核 findings" />
          </template>
        </el-table>
        <el-empty
          v-else-if="!reviewLoading"
          :image-size="70"
          description="未找到可复核的 findings；可仍提交空决策以推进报告阶段"
        />

        <div class="toolbar" style="margin-top: 16px">
          <div class="grow" />
          <el-button @click="drawer = false">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="submitDecisions">
            提交决策并恢复扫描
          </el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { api, errorMessage } from '@/api/client'
import type { GraphFinding, GraphResponse } from '@/api/types'
import ErrorAlert from '@/components/ErrorAlert.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'

interface ReviewRow {
  id: number
  repo_path: string
  status: string
  created?: string
}

interface PendingFinding extends GraphFinding {
  _verdict: 'approve' | 'reject' | 'adjust'
  _confidence: number
}

const loading = ref(false)
const error = ref('')
const queue = ref<ReviewRow[]>([])

const drawer = ref(false)
const reviewScan = ref<ReviewRow | null>(null)
const reviewLoading = ref(false)
const reviewError = ref('')
const reviewNote = ref('')
const pending = ref<PendingFinding[]>([])
const submitting = ref(false)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const res = await api.get<{ queue: ReviewRow[] }>('/api/reviews')
    queue.value = res?.queue ?? []
  } catch (e) {
    error.value = `加载复核队列失败：${errorMessage(e)}`
  } finally {
    loading.value = false
  }
}

function collectFindings(payload: unknown): GraphFinding[] | null {
  if (Array.isArray(payload)) return payload as GraphFinding[]
  if (payload && typeof payload === 'object') {
    const list = (payload as { findings?: unknown }).findings
    if (Array.isArray(list)) return list as GraphFinding[]
  }
  return null
}

function fromGraph(graph: GraphResponse | null): GraphFinding[] {
  const map = new Map<number, GraphFinding>()
  for (const node of graph?.nodes ?? []) {
    for (const finding of node.findings ?? []) {
      if (finding?.id !== undefined) map.set(finding.id, finding)
    }
  }
  return [...map.values()]
}

async function openReview(row: ReviewRow): Promise<void> {
  reviewScan.value = row
  drawer.value = true
  reviewLoading.value = true
  reviewError.value = ''
  reviewNote.value = ''
  pending.value = []
  try {
    const [findingsRes, graphRes] = await Promise.allSettled([
      api.get<unknown>(`/api/scans/${row.id}/findings`),
      api.get<GraphResponse>(`/api/scans/${row.id}/graph`),
    ])
    const fromApi = findingsRes.status === 'fulfilled' ? collectFindings(findingsRes.value) : null
    const graph = graphRes.status === 'fulfilled' ? graphRes.value : null
    const list = fromApi ?? fromGraph(graph)
    if (!fromApi) {
      reviewNote.value = list.length
        ? 'findings 端点不可用，待复核项已从 graph 节点聚合。'
        : 'findings 与 graph 均未返回待复核项。'
    }
    pending.value = list.map((finding) => ({
      ...finding,
      _verdict: 'approve',
      _confidence:
        typeof finding.confidence === 'number' ? Math.min(1, Math.max(0, finding.confidence)) : 0.5,
    }))
  } catch (e) {
    reviewError.value = `加载待复核 findings 失败：${errorMessage(e)}`
  } finally {
    reviewLoading.value = false
  }
}

function bulk(verdict: 'approve' | 'reject'): void {
  for (const item of pending.value) {
    item._verdict = verdict
    if (verdict === 'reject') item._confidence = 0
  }
}

async function submitDecisions(): Promise<void> {
  if (!reviewScan.value) return
  const decisions = pending.value.map((item) => {
    const base: Record<string, unknown> = {
      rule_id: item.rule_id,
      line: item.line,
      verdict: item._verdict,
    }
    if (item._verdict !== 'reject') base.confidence = item._confidence
    return base
  })
  try {
    await ElMessageBox.confirm(
      `将提交 ${decisions.length} 条决策并恢复扫描 #${reviewScan.value.id} 的执行，是否继续？`,
      '提交复核决策',
      { type: 'warning', confirmButtonText: '提交', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  submitting.value = true
  try {
    const res = await api.post<{ ok: boolean; phase?: string; kept?: number }>(
      `/api/scans/${reviewScan.value.id}/resume`,
      { decisions },
    )
    ElMessage.success(
      `扫描已恢复：phase=${res.phase ?? 'unknown'}，保留 ${res.kept ?? 0} 条 findings`,
    )
    drawer.value = false
    await load()
  } catch (e) {
    reviewError.value = `提交失败：${errorMessage(e)}`
    ElMessage.error(errorMessage(e))
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>
