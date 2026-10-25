<template>
  <div>
    <page-header
      :title="`审计工作台 · 扫描 #${scanId}`"
      :subtitle="scan?.repo_path || 'Agent 图审计过程与证据'"
    >
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button @click="router.push(`/scans/${scanId}`)">扫描详情</el-button>
        <el-button type="primary" @click="router.push(`/scans/${scanId}/graph`)">代码图</el-button>
      </template>
    </page-header>

    <error-alert :message="error" @retry="load" />

    <div class="panel workbench-head">
      <status-tag :status="scan?.status" effect="dark" />
      <el-tag effect="plain">路径 {{ coverage.total ?? 0 }}</el-tag>
      <el-tag type="success" effect="plain">已审 {{ coverage.done ?? 0 }}</el-tag>
      <el-tag type="warning" effect="plain">待审 {{ coverage.pending ?? 0 }}</el-tag>
      <el-tag type="danger" effect="plain" v-if="coverage.timeout">超时 {{ coverage.timeout }}</el-tag>
      <el-tag effect="plain">Findings {{ findings.length }}</el-tag>
      <el-tag type="success" effect="plain">verified {{ verifiedCount }}</el-tag>
      <el-tag type="info" effect="plain">tokens {{ totalTokens }}</el-tag>
      <div class="grow" />
      <el-button size="small" :disabled="scan?.status !== 'running'" @click="control('pause')">暂停</el-button>
      <el-button size="small" :disabled="scan?.status !== 'running'" @click="control('resume')">恢复</el-button>
      <el-button size="small" type="danger" :disabled="scan?.status !== 'running'" @click="control('stop')">停止</el-button>
      <el-tag v-if="controlState?.paused" type="warning" size="small">已暂停</el-tag>
      <el-tag v-if="controlState?.stop_requested" type="danger" size="small">停止中</el-tag>
    </div>

    <el-row :gutter="12">
      <el-col :xs="24" :md="5">
        <div class="panel workbench-col">
          <h3 class="panel-title">Agent 树</h3>
          <el-scrollbar height="560px">
            <div
              v-for="node in treeRows"
              :key="node.agent_key"
              class="agent-node"
              :class="{ active: eventFilter.agent === node.name }"
              :style="{ paddingLeft: `${8 + node.depth * 14}px` }"
              @click="eventFilter.agent = eventFilter.agent === node.name ? '' : node.name"
            >
              <el-tag size="small" :type="node.status === 'ok' ? 'success' : node.status === 'failed' ? 'danger' : 'info'">
                {{ node.status }}
              </el-tag>
              <span class="mono">{{ node.name }}</span>
              <span class="muted">{{ node.tokens || 0 }} tok</span>
            </div>
            <el-empty v-if="!tree.length" :image-size="50" description="暂无 Agent 节点" />
          </el-scrollbar>
        </div>
      </el-col>

      <el-col :xs="24" :md="12">
        <div class="panel workbench-col">
          <div class="toolbar">
            <h3 class="panel-title" style="margin: 0">审计事件流</h3>
            <el-select v-model="eventFilter.type" size="small" clearable placeholder="事件类型" style="width: 150px">
              <el-option v-for="t in eventTypes" :key="t" :label="t" :value="t" />
            </el-select>
            <el-checkbox v-model="autoScroll" size="small">自动滚动</el-checkbox>
            <span class="muted">{{ filteredEvents.length }} 条</span>
            <div class="grow" />
            <el-button size="small" @click="events = []">清空</el-button>
          </div>
          <el-scrollbar ref="streamRef" height="540px" @scroll="onStreamScroll">
            <div
              v-for="event in filteredEvents"
              :key="`${event.seq}-${event.event_type}`"
              class="event-row"
              :class="{
                active: selectedEvent?.seq === event.seq,
                'event-finding': event.event_type.includes('finding') || event.event_type.includes('verified'),
                'event-tool': event.event_type.includes('tool'),
                'event-verify': event.event_type.includes('verification'),
                'event-path': event.event_type.includes('path'),
                'event-error': event.event_type.includes('error') || event.event_type.includes('timeout'),
                'event-supervisor': event.event_type.includes('supervisor'),
              }"
              @click="selectedEvent = event"
            >
              <div class="event-meta">
                <el-tag size="small" effect="plain">{{ event.event_type }}</el-tag>
                <span class="mono muted">{{ event.agent || 'system' }}</span>
                <span class="muted">{{ event.created_at || '' }}</span>
              </div>
              <div class="event-text">{{ eventSummary(event) }}</div>
            </div>
            <el-empty v-if="!filteredEvents.length" :image-size="60" description="暂无审计事件" />
          </el-scrollbar>
        </div>
      </el-col>

      <el-col :xs="24" :md="7">
        <div class="panel workbench-col">
          <h3 class="panel-title">上下文</h3>
          <template v-if="selectedEvent">
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="event">{{ selectedEvent.event_type }}</el-descriptions-item>
              <el-descriptions-item label="agent">{{ selectedEvent.agent || '—' }}</el-descriptions-item>
              <el-descriptions-item label="seq">{{ selectedEvent.seq }}</el-descriptions-item>
            </el-descriptions>
            <json-block :value="selectedEvent.payload ?? {}" />
          </template>
          <template v-else-if="selectedPath">
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="path">#{{ selectedPath.id }}</el-descriptions-item>
              <el-descriptions-item label="entry">{{ selectedPath.entry_key }}</el-descriptions-item>
              <el-descriptions-item label="sink">{{ selectedPath.sink_key }}</el-descriptions-item>
              <el-descriptions-item label="feasibility">{{ selectedPath.feasibility }}</el-descriptions-item>
              <el-descriptions-item label="status">{{ selectedPath.status }}</el-descriptions-item>
            </el-descriptions>
            <el-button size="small" style="margin-top: 8px" @click="router.push(`/scans/${scanId}/graph?path_id=${selectedPath.id}`)">
              图中高亮
            </el-button>
            <json-block :value="selectedPath.evidence ?? {}" />
          </template>
          <template v-else-if="selectedFinding">
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="rule">{{ selectedFinding.rule_id }}</el-descriptions-item>
              <el-descriptions-item label="cwe">{{ selectedFinding.cwe }}</el-descriptions-item>
              <el-descriptions-item label="severity">{{ selectedFinding.severity }}</el-descriptions-item>
              <el-descriptions-item label="file">{{ selectedFinding.file }}:{{ selectedFinding.line }}</el-descriptions-item>
              <el-descriptions-item label="verdict">{{ selectedFinding.verdict || '—' }}</el-descriptions-item>
            </el-descriptions>
            <p class="muted">{{ selectedFinding.message }}</p>
            <el-button size="small" @click="router.push(`/scans/${scanId}`)">打开 Finding 详情</el-button>
          </template>
          <el-empty v-else :image-size="60" description="点击事件 / 路径 / finding 查看上下文" />
        </div>
      </el-col>
    </el-row>

    <div class="panel">
      <el-tabs v-model="tab">
        <el-tab-pane label="路径" name="paths">
          <el-table :data="paths" size="small" max-height="360" @row-click="selectedPath = $event">
            <el-table-column prop="id" label="#" width="60" />
            <el-table-column prop="entry_key" label="入口" min-width="220" show-overflow-tooltip />
            <el-table-column prop="sink_key" label="Sink" min-width="220" show-overflow-tooltip />
            <el-table-column prop="feasibility" label="可行性" width="90" />
            <el-table-column prop="status" label="状态" width="90" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="Findings" name="findings">
          <el-table :data="findings" size="small" max-height="360" @row-click="selectedFinding = $event">
            <el-table-column prop="rule_id" label="规则" width="130" />
            <el-table-column prop="cwe" label="CWE" width="80" />
            <el-table-column prop="severity" label="级别" width="80" />
            <el-table-column prop="file" label="文件" min-width="220" show-overflow-tooltip />
            <el-table-column prop="verdict" label="结论" width="100" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="验证" name="verifications">
          <el-table :data="verifications" size="small" max-height="360">
            <el-table-column prop="id" label="#" width="60" />
            <el-table-column prop="cwe" label="CWE" width="80" />
            <el-table-column prop="language" label="语言" width="100" />
            <el-table-column prop="verdict" label="结论" width="100" />
            <el-table-column prop="status" label="状态" width="100" />
            <el-table-column prop="stdout" label="输出" min-width="260" show-overflow-tooltip />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="工具证据" name="tools">
          <div class="toolbar">
            <span class="muted">外部工具结果只作为证据，不直接成为 finding。</span>
            <div class="grow" />
            <el-button v-for="t in tools" :key="t.name" size="small"
                       :disabled="!t.available || t.network && !t.network_enabled"
                       :loading="toolRunning === t.name"
                       @click="runTool(t.name)">
              {{ t.name }}
            </el-button>
          </div>
          <el-table :data="toolRuns" size="small" max-height="320">
            <el-table-column prop="tool" label="工具" width="120" />
            <el-table-column prop="status" label="状态" width="100" />
            <el-table-column label="数量" width="80">
              <template #default="{ row }">{{ row.result?.count ?? 0 }}</template>
            </el-table-column>
            <el-table-column prop="duration_ms" label="耗时" width="90" />
            <el-table-column label="证据" min-width="260" show-overflow-tooltip>
              <template #default="{ row }">{{ JSON.stringify(row.evidence || []).slice(0, 300) }}</template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="报告" name="report">
          <div class="toolbar">
            <el-button @click="router.push(`/scans/${scanId}`)">扫描详情</el-button>
            <el-button @click="openHtml">HTML 报告</el-button>
            <el-button @click="downloadEvidence">下载证据包</el-button>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { api, errorMessage } from '@/api/client'
import type { FindingDetail, GraphFinding, ScanRow } from '@/api/types'
import ErrorAlert from '@/components/ErrorAlert.vue'
import JsonBlock from '@/components/JsonBlock.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'

interface AgentEvent {
  seq: number
  event_type: string
  event?: string
  agent?: string
  phase?: string
  payload?: Record<string, unknown>
  created_at?: string
}

interface AgentNode {
  agent_key: string
  parent_key?: string
  depth?: number
  name: string
  phase?: string
  status?: string
  tokens?: number
  tool_calls?: number
  summary?: string
}

interface AuditPath {
  id: number
  entry_key: string
  sink_key: string
  feasibility: string
  status: string
  evidence?: unknown
}

interface VerificationRow {
  id: number
  cwe: number
  language: string
  verdict: string
  status: string
  stdout: string
}

const route = useRoute()
const router = useRouter()
const scanId = computed(() => Number(route.params.id || 0))
const scan = ref<ScanRow | null>(null)
const coverage = ref<Record<string, unknown>>({})
const findings = ref<GraphFinding[]>([])
const paths = ref<AuditPath[]>([])
const tree = ref<AgentNode[]>([])
const verifications = ref<VerificationRow[]>([])
const tools = ref<Array<{ name: string; available: boolean; network: boolean; network_enabled?: boolean }>>([])
const toolRuns = ref<Array<Record<string, unknown>>>([])
const toolRunning = ref('')
const events = ref<AgentEvent[]>([])
const controlState = ref<Record<string, unknown> | null>(null)
const selectedEvent = ref<AgentEvent | null>(null)
const selectedPath = ref<AuditPath | null>(null)
const selectedFinding = ref<GraphFinding | null>(null)
const tab = ref('paths')
const loading = ref(false)
const error = ref('')
const autoScroll = ref(true)
const streamRef = ref<{ setScrollTop: (v: number) => void; wrapRef?: HTMLElement } | null>(null)
const eventFilter = reactive({ agent: '', type: '' })
let source: EventSource | null = null
let pollTimer: number | undefined

const treeRows = computed(() => {
  const byKey = new Map(tree.value.map((n) => [n.agent_key, n]))
  const depthOf = (node: AgentNode, seen = new Set<string>()): number => {
    let depth = 0
    let parent = node.parent_key
    while (parent && byKey.has(parent) && !seen.has(parent)) {
      seen.add(parent)
      depth += 1
      parent = byKey.get(parent)?.parent_key
    }
    return depth
  }
  return tree.value.map((n) => ({ ...n, depth: depthOf(n) }))
})

const verifiedCount = computed(() =>
  findings.value.filter((f) => f.verdict === 'verified').length,
)
const totalTokens = computed(() =>
  tree.value.reduce((sum, n) => sum + Number(n.tokens || 0), 0),
)
const eventTypes = computed(() => [...new Set(events.value.map((e) => e.event_type))].sort())
const filteredEvents = computed(() =>
  events.value
    .filter((e) => !eventFilter.agent || e.agent === eventFilter.agent)
    .filter((e) => !eventFilter.type || e.event_type === eventFilter.type)
    .slice(-1000),
)

function eventSummary(event: AgentEvent): string {
  const payload = event.payload || {}
  const bits = [
    payload.message,
    payload.reason,
    payload.node,
    payload.tool,
    payload.status,
    payload.path_id ? `path#${payload.path_id}` : '',
  ].filter(Boolean)
  return bits.length ? bits.join(' · ') : JSON.stringify(payload).slice(0, 220)
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [s, cover, f, p, t, v, ctrl, tl] = await Promise.allSettled([
      api.get<ScanRow>(`/api/scans/${scanId.value}`),
      api.get<Record<string, unknown>>(`/api/scans/${scanId.value}/coverage`),
      api.get<{ findings?: GraphFinding[] }>(`/api/scans/${scanId.value}/findings`),
      api.get<{ paths?: AuditPath[] }>(`/api/scans/${scanId.value}/paths`, { limit: 300 }),
      api.get<{ nodes?: AgentNode[] }>(`/api/scans/${scanId.value}/agent-tree`),
      api.get<{ runs?: VerificationRow[] }>(`/api/scans/${scanId.value}/verifications`),
      api.get<Record<string, unknown>>(`/api/scans/${scanId.value}/control`),
      api.get<{ tools?: Array<Record<string, unknown>>; runs?: Array<Record<string, unknown>> }>(
        `/api/scans/${scanId.value}/tools`,
      ),
    ])
    scan.value = s.status === 'fulfilled' ? s.value : null
    coverage.value = cover.status === 'fulfilled' ? cover.value : {}
    findings.value = f.status === 'fulfilled' ? (f.value.findings || []) : []
    paths.value = p.status === 'fulfilled' ? (p.value.paths || []) : []
    tree.value = t.status === 'fulfilled' ? (t.value.nodes || []) : []
    verifications.value = v.status === 'fulfilled' ? (v.value.runs || []) : []
    controlState.value = ctrl.status === 'fulfilled' ? ctrl.value : null
    tools.value = tl.status === 'fulfilled' ? ((tl.value.tools || []) as never) : []
    toolRuns.value = tl.status === 'fulfilled' ? (tl.value.runs || []) : []
  } catch (e) {
    error.value = `加载工作台失败：${errorMessage(e)}`
  } finally {
    loading.value = false
  }
}

async function loadEvents(afterSeq = 0): Promise<void> {
  try {
    const res = await api.get<{ events?: AgentEvent[] }>(
      `/api/scans/${scanId.value}/events`, { after_seq: afterSeq, limit: 300 },
    )
    const incoming = res.events || []
    if (incoming.length) {
      const seen = new Set(events.value.map((e) => e.seq))
      events.value = [...events.value, ...incoming.filter((e) => !seen.has(e.seq))]
        .sort((a, b) => a.seq - b.seq).slice(-2000)
    }
  } catch {
    // SSE will retry
  }
}

function connectStream(): void {
  source?.close()
  source = new EventSource(`/api/scans/${scanId.value}/events/stream?after_seq=0`)
  source.onmessage = (message) => {
    try {
      const event = JSON.parse(message.data) as AgentEvent
      if (!events.value.some((e) => e.seq === event.seq)) {
        events.value.push(event)
        events.value = events.value.slice(-2000)
      }
    } catch {
      // ignore malformed event
    }
  }
}

function onStreamScroll(): void {
  autoScroll.value = false
}

watch(
  () => events.value.length,
  async () => {
    if (!autoScroll.value) return
    await nextTick()
    const el = streamRef.value?.wrapRef
    if (el) el.scrollTop = el.scrollHeight
  },
)

async function control(action: 'pause' | 'resume' | 'stop'): Promise<void> {
  try {
    await api.post(`/api/scans/${scanId.value}/${action}`)
    ElMessage.success(`已请求 ${action}`)
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function runTool(name: string): Promise<void> {
  toolRunning.value = name
  try {
    const res = await api.post<Record<string, unknown>>(`/api/scans/${scanId.value}/tools/${name}`)
    ElMessage.success(`工具 ${name}: ${String(res.status || 'done')}`)
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    toolRunning.value = ''
  }
}

function openHtml(): void {
  window.open(`/api/scans/${scanId.value}/report/html`, '_blank', 'noopener')
}

function downloadEvidence(): void {
  window.location.href = `/api/scans/${scanId.value}/evidence/export`
}

function schedulePoll(): void {
  if (pollTimer) window.clearTimeout(pollTimer)
  if (scan.value?.status === 'running') {
    pollTimer = window.setTimeout(async () => {
      await Promise.all([load(), loadEvents(Math.max(0, ...events.value.map((e) => e.seq)))])
      schedulePoll()
    }, 5000)
  }
}

onMounted(async () => {
  await load()
  await loadEvents(0)
  connectStream()
  schedulePoll()
})
onUnmounted(() => {
  source?.close()
  if (pollTimer) window.clearTimeout(pollTimer)
})
</script>

<style scoped>
.workbench-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.workbench-col {
  height: 620px;
  overflow: hidden;
}
.agent-node {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 4px;
  border-bottom: 1px solid var(--cs-border);
  cursor: pointer;
}
.agent-node.active {
  background: rgba(37, 99, 235, 0.08);
}
.event-row {
  padding: 7px 8px;
  border-bottom: 1px solid var(--cs-border);
  border-left: 2px solid transparent;
  cursor: pointer;
  font-family: var(--cs-mono);
}
.event-row.event-finding { border-left-color: var(--cs-red); background: rgba(239,68,68,.035); }
.event-row.event-tool { border-left-color: var(--cs-cyan); }
.event-row.event-verify { border-left-color: var(--cs-green); background: rgba(34,197,94,.035); }
.event-row.event-path { border-left-color: var(--cs-accent); }
.event-row.event-error { border-left-color: var(--cs-red); background: rgba(239,68,68,.07); }
.event-row.event-supervisor { border-left-color: var(--cs-purple); background: rgba(167,139,250,.035); }
.event-row.active {
  background: rgba(37, 99, 235, 0.08);
}
.event-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 11px;
}
.event-text {
  margin-top: 4px;
  font-size: 12px;
  color: var(--cs-text-muted);
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
