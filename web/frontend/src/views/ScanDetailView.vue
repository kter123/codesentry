<template>
  <div>
    <page-header
      :title="scan ? `扫描 #${scan.id}` : `扫描 #${scanId}`"
      :subtitle="scan?.repo_path || '加载扫描信息…'"
    >
      <template #actions>
        <el-button @click="$router.push('/scans')">
          <el-icon><Back /></el-icon>
          <span>返回列表</span>
        </el-button>
        <el-button :loading="loading" @click="load()">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
        <el-button type="primary" @click="assistVisible = true">问 AI</el-button>
      </template>
    </page-header>

    <el-result
      v-if="notFound"
      icon="warning"
      title="扫描不存在"
      sub-title="该扫描可能已被删除，或 ID 不正确。"
    >
      <template #extra>
        <el-button type="primary" @click="$router.push('/scans')">返回扫描列表</el-button>
      </template>
    </el-result>

    <template v-else>
      <error-alert :message="error" @retry="load()" />

      <div class="stat-grid">
        <div class="stat-card">
          <span class="stat-label">状态</span>
          <span class="stat-value"><status-tag :status="scan?.status" effect="dark" /></span>
          <span class="stat-hint">{{ scan?.status === 'running' ? '运行中，自动刷新' : '当前扫描状态' }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">模式</span>
          <span class="stat-value">{{ scan?.mode || '—' }}</span>
          <span class="stat-hint">OSS：{{ scan?.OSS ? '是' : '否' }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">Findings</span>
          <span class="stat-value">{{ findings.length }}</span>
          <span class="stat-hint">{{ findingNote || '来自 findings / graph 聚合' }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">图节点 / 边</span>
          <span class="stat-value">{{ graph?.nodes?.length ?? 0 }} / {{ graph?.edges?.length ?? 0 }}</span>
          <span class="stat-hint">模式：{{ graph?.mode || '不可用' }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">时间线节点</span>
          <span class="stat-value">{{ timelineNodes.length }}</span>
          <span class="stat-hint">{{ timelineSource }}</span>
        </div>
      </div>

      <div class="panel">
        <h2 class="panel-title">部署信息 <span class="panel-subtitle">DeployAgent / 沙箱</span></h2>
        <template v-if="hasDeployInfo">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="deploy_status">
              <status-tag :status="scan?.deploy_status" />
            </el-descriptions-item>
            <el-descriptions-item label="target_url">
              <el-link
                v-if="scan?.target_url"
                type="primary"
                :href="scan.target_url"
                target="_blank"
                rel="noopener noreferrer"
              >
                {{ scan.target_url }}
              </el-link>
              <span v-else class="muted">—</span>
            </el-descriptions-item>
          </el-descriptions>
          <pre v-if="scan?.deploy_log" class="pre-block light" style="margin-top: 12px">{{
            scan.deploy_log
          }}</pre>
        </template>
        <el-empty
          v-else
          :image-size="56"
          description="该扫描没有部署信息（未启用 DeployAgent 或为历史扫描）"
        />
        <el-alert
          v-if="scan?.error_reason"
          type="error"
          show-icon
          :closable="false"
          :title="`失败原因：${scan.error_reason}`"
        />
      </div>

      <div class="panel">
        <el-tabs v-model="activeTab">
          <el-tab-pane label="时间线" name="timeline">
            <div v-loading="loading">
              <el-timeline v-if="timelineNodes.length">
                <el-timeline-item
                  v-for="(node, index) in timelineNodes"
                  :key="`${node.node}-${index}`"
                  :timestamp="node.started || ''"
                  placement="top"
                  :type="node.status === 'ok' ? 'success' : node.status === 'failed' ? 'danger' : 'primary'"
                >
                  <div class="timeline-card">
                    <div class="timeline-head">
                      <strong>{{ node.node }}</strong>
                      <status-tag :status="node.status" />
                      <span class="muted mono">{{ fmtDuration(node.duration_ms) }}</span>
                      <span class="muted mono">{{ node.tokens ?? 0 }} tokens</span>
                      <span v-if="node.tool_calls" class="muted mono">
                        {{ node.tool_calls }} tool calls
                      </span>
                    </div>
                    <div v-if="node.ended" class="muted mono">ended: {{ node.ended }}</div>
                    <el-alert
                      v-if="node.error"
                      type="error"
                      :title="node.error"
                      :closable="false"
                      show-icon
                      style="margin-top: 8px"
                    />
                  </div>
                </el-timeline-item>
              </el-timeline>
              <el-empty v-else description="暂无节点运行记录" :image-size="70" />
            </div>
          </el-tab-pane>

          <el-tab-pane label="审查链" name="artifacts">
            <div class="toolbar">
              <el-button size="small" :loading="artifactLoading" @click="loadArtifacts">刷新</el-button>
              <el-button size="small" :disabled="!artifacts.length" @click="verifyArtifacts">
                哈希链校验
              </el-button>
              <status-tag v-if="artifactVerify" :status="artifactVerify.ok ? 'ok' : 'failed'" />
              <span class="muted">{{ artifacts.length }} 个节点产物</span>
            </div>
            <el-timeline v-if="artifacts.length">
              <el-timeline-item
                v-for="a in artifacts"
                :key="a.seq"
                :timestamp="a.created_at"
                placement="top"
              >
                <div class="timeline-card">
                  <div class="timeline-head">
                    <strong>{{ a.node }}</strong>
                    <span class="muted mono">#{{ a.seq }}</span>
                    <span class="muted mono">{{ a.model || '—' }}</span>
                    <span class="muted mono">{{ a.tokens }} tokens</span>
                  </div>
                  <el-collapse>
                    <el-collapse-item title="输入摘要" :name="`in-${a.seq}`">
                      <pre class="pre-block light">{{ a.input_preview }}</pre>
                    </el-collapse-item>
                    <el-collapse-item title="输出摘要" :name="`out-${a.seq}`">
                      <pre class="pre-block light">{{ a.output_preview }}</pre>
                    </el-collapse-item>
                  </el-collapse>
                </div>
              </el-timeline-item>
            </el-timeline>
            <el-empty v-else description="暂无审查链产物（扫描完成或进行中后刷新）" :image-size="70" />
            <div v-if="liveEvents.length" class="panel" style="margin-top: 14px">
              <h2 class="panel-title">实时 Agent 事件</h2>
              <div
                v-for="(e, i) in liveEvents.slice(-12)"
                :key="i"
                class="mono muted"
                style="font-size: 12px; padding: 2px 0"
              >
                {{ e.event }} · {{ e.node || '' }} · {{ e.status || '' }}
                <span v-if="e.tokens">· {{ e.tokens }} tokens</span>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="调用图" name="graph">
            <template v-if="graph">
              <div class="toolbar">
                <el-tag effect="plain">模式：{{ graph.mode || 'unknown' }}</el-tag>
                <el-tag v-for="lang in graph.languages || []" :key="lang" effect="plain">
                  {{ lang }}
                </el-tag>
                <span class="muted">{{ graph.nodes?.length ?? 0 }} 节点 / {{ graph.edges?.length ?? 0 }} 边</span>
              </div>
              <el-table :data="graph.nodes || []" size="small" max-height="520">
                <el-table-column prop="id" label="节点 ID" min-width="260" show-overflow-tooltip />
                <el-table-column prop="kind" label="类型" width="100" />
                <el-table-column prop="file" label="文件" min-width="220" show-overflow-tooltip />
                <el-table-column prop="name" label="符号" min-width="140" show-overflow-tooltip />
                <el-table-column label="行范围" width="110">
                  <template #default="{ row }">{{ row.start || 0 }}-{{ row.end || 0 }}</template>
                </el-table-column>
                <el-table-column label="findings" width="100">
                  <template #default="{ row }">
                    <el-tag size="small" :type="row.findings?.length ? 'danger' : 'info'">
                      {{ row.findings?.length || 0 }}
                    </el-tag>
                  </template>
                </el-table-column>
                <template #empty>
                  <el-empty description="图为空：仓库未检测到 Python 调用图，或没有 findings" />
                </template>
              </el-table>
            </template>
            <el-empty v-else description="调用图接口不可用或返回失败" :image-size="70" />
          </el-tab-pane>

          <el-tab-pane label="Findings" name="findings">
            <el-alert
              v-if="findingNote"
              type="info"
              :title="findingNote"
              :closable="false"
              show-icon
              style="margin-bottom: 12px"
            />
            <el-table
              v-loading="loading"
              :data="findings"
              size="small"
              row-key="id"
              max-height="560"
              @row-click="openFinding"
            >
              <el-table-column prop="id" label="ID" width="70" />
              <el-table-column prop="rule_id" label="规则" min-width="170" show-overflow-tooltip />
              <el-table-column prop="severity" label="严重度" width="100">
                <template #default="{ row }"><status-tag :status="row.severity" /></template>
              </el-table-column>
              <el-table-column prop="verdict" label="结论" width="110">
                <template #default="{ row }"><status-tag :status="row.verdict" /></template>
              </el-table-column>
              <el-table-column label="置信度" width="110">
                <template #default="{ row }">
                  {{ row.confidence === undefined || row.confidence === null ? '—' : Number(row.confidence).toFixed(2) }}
                </template>
              </el-table-column>
              <el-table-column label="位置" min-width="220" show-overflow-tooltip>
                <template #default="{ row }">
                  <span class="mono">{{ row.file_rel || row.file || '—' }}:{{ row.line ?? '—' }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="message" label="描述" min-width="260" show-overflow-tooltip />
              <template #empty>
                <el-empty
                  :image-size="80"
                  description="没有 findings（扫描可能仍在运行，或该扫描未产出结果）"
                />
              </template>
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </div>
    </template>

    <el-drawer v-model="drawer" title="Finding 详情" size="62%" destroy-on-close>
      <div v-loading="detailLoading">
        <template v-if="selected">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="ID">{{ selected.id }}</el-descriptions-item>
            <el-descriptions-item label="规则">{{ selected.rule_id || '—' }}</el-descriptions-item>
            <el-descriptions-item label="严重度">
              <status-tag :status="selected.severity" />
            </el-descriptions-item>
            <el-descriptions-item label="结论">
              <status-tag :status="selected.verdict" />
            </el-descriptions-item>
            <el-descriptions-item label="CWE">{{ selected.cwe || '—' }}</el-descriptions-item>
            <el-descriptions-item label="引擎">{{ selected.engine || '—' }}</el-descriptions-item>
            <el-descriptions-item label="置信度">
              {{ selected.confidence === undefined || selected.confidence === null ? '—' : Number(selected.confidence).toFixed(3) }}
            </el-descriptions-item>
            <el-descriptions-item label="PoC 路径">{{ selected.poc_path || '—' }}</el-descriptions-item>
            <el-descriptions-item label="文件" :span="2">
              <span class="mono">{{ selected.file || selected.file_rel || '—' }}:{{ selected.line ?? '—' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="描述" :span="2">{{ selected.message || '—' }}</el-descriptions-item>
          </el-descriptions>

          <h3 class="panel-title" style="margin-top: 18px">源码上下文</h3>
          <div v-if="sourceLines.length" class="source-view">
            <div
              v-for="line in sourceLines"
              :key="line.no"
              class="source-line"
              :class="{ target: line.no === selected.line }"
            >
              <span class="source-no">{{ line.no }}</span>
              <span class="source-text">{{ line.text }}</span>
            </div>
          </div>
          <el-empty v-else :image-size="56" description="无法加载源码切片（文件可能不在 work 目录）" />

          <h3 class="panel-title" style="margin-top: 18px">污点与利用链</h3>
          <json-block :value="selected.taint_metadata ?? null" />
          <json-block :value="selected.exploit_chain ?? null" />

          <template v-if="selected.confidence_parts">
            <h3 class="panel-title" style="margin-top: 18px">置信度分解</h3>
            <json-block :value="selected.confidence_parts" />
          </template>

          <template v-if="selected.tool_trace">
            <h3 class="panel-title" style="margin-top: 18px">Agent 工具轨迹</h3>
            <json-block :value="selected.tool_trace" />
          </template>

          <template v-if="selected.verification_method">
            <h3 class="panel-title" style="margin-top: 18px">PoC 实证</h3>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="方法">{{ selected.verification_method }}</el-descriptions-item>
              <el-descriptions-item label="Nonce">{{ selected.verification_nonce || '—' }}</el-descriptions-item>
            </el-descriptions>
          </template>

          <template v-if="selected.execution_log">
            <h3 class="panel-title" style="margin-top: 18px">执行日志</h3>
            <pre class="pre-block">{{ selected.execution_log }}</pre>
          </template>

          <el-button
            v-if="selected.scan_id || scanId"
            style="margin-top: 16px"
            @click="$router.push('/scans')"
          >
            返回扫描列表
          </el-button>
        </template>
        <el-empty v-else description="未能加载 finding 详情" />
      </div>
    </el-drawer>

    <el-drawer v-model="assistVisible" title="Ask CodeSentry" size="46%" destroy-on-close>
      <el-input
        v-model="assistQuestion"
        type="textarea"
        :rows="4"
        placeholder="例如：这个 SSRF finding 为什么被判为可达？有哪些证据？"
      />
      <el-button
        type="primary"
        style="margin-top: 10px"
        :loading="assistLoading"
        :disabled="!assistQuestion.trim()"
        @click="askAssist"
      >
        提问
      </el-button>
      <el-alert
        v-if="assistError"
        type="error"
        :title="assistError"
        :closable="false"
        show-icon
        style="margin-top: 10px"
      />
      <pre v-if="assistAnswer" class="pre-block light" style="margin-top: 14px">{{ assistAnswer }}</pre>
      <div v-if="assistSources.length" class="muted mono" style="margin-top: 10px; font-size: 12px">
        来源：{{ assistSources.map((s) => `${s.type}:${s.node || s.rule_id || ''}`).join(' · ') }}
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Back, Refresh } from '@element-plus/icons-vue'

import { api, ApiError, errorMessage } from '@/api/client'
import type {
  FindingDetail,
  GraphFinding,
  GraphResponse,
  NodeRun,
  ScanRow,
} from '@/api/types'
import ErrorAlert from '@/components/ErrorAlert.vue'
import JsonBlock from '@/components/JsonBlock.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'

interface SourceLine {
  no: number
  text: string
}

interface ArtifactRow {
  seq: number
  node: string
  input_preview: string
  output_preview: string
  model: string
  tokens: number
  prev_sha256: string
  created_at: string
}

interface LiveEvent {
  event: string
  node?: string
  status?: string
  tokens?: number
  duration_ms?: number
}

const route = useRoute()
const scanId = computed(() => Number(route.params.id))

const scan = ref<ScanRow | null>(null)
const timelineNodes = ref<NodeRun[]>([])
const timelineSource = ref('')
const graph = ref<GraphResponse | null>(null)
const findings = ref<GraphFinding[]>([])
const findingNote = ref('')
const loading = ref(false)
const error = ref('')
const notFound = ref(false)
const activeTab = ref('timeline')

const drawer = ref(false)
const selected = ref<FindingDetail | null>(null)
const detailLoading = ref(false)
const sourceLines = ref<SourceLine[]>([])
const artifacts = ref<ArtifactRow[]>([])
const artifactVerify = ref<{ ok: boolean; count?: number; broken_at?: number } | null>(null)
const artifactLoading = ref(false)
const liveEvents = ref<LiveEvent[]>([])
const assistVisible = ref(false)
const assistQuestion = ref('')
const assistLoading = ref(false)
const assistError = ref('')
const assistAnswer = ref('')
const assistSources = ref<Array<{ type: string; node?: string; rule_id?: string }>>([])
let socket: WebSocket | undefined

let pollTimer: number | undefined

const hasDeployInfo = computed(() => {
  const value = scan.value
  if (!value) return false
  return Boolean(value.deploy_status || value.target_url || value.deploy_log)
})

function fmtDuration(ms?: number): string {
  if (ms === undefined || ms === null) return '—'
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(2)} s`
}

async function loadArtifacts(): Promise<void> {
  artifactLoading.value = true
  try {
    const res = await api.get<{ artifacts?: ArtifactRow[] }>(
      `/api/scans/${scanId.value}/artifacts`,
    )
    artifacts.value = Array.isArray(res?.artifacts) ? res.artifacts : []
  } catch {
    artifacts.value = []
  } finally {
    artifactLoading.value = false
  }
}

async function verifyArtifacts(): Promise<void> {
  try {
    artifactVerify.value = await api.get<{ ok: boolean; count?: number; broken_at?: number }>(
      `/api/scans/${scanId.value}/artifacts/verify`,
    )
  } catch (e) {
    artifactVerify.value = { ok: false }
    error.value = `审查链校验失败：${errorMessage(e)}`
  }
}

async function askAssist(): Promise<void> {
  assistLoading.value = true
  assistError.value = ''
  assistAnswer.value = ''
  assistSources.value = []
  try {
    const res = await api.post<{ answer?: string; sources?: Array<{ type: string; node?: string; rule_id?: string }> }>(
      '/api/assist/ask',
      { question: assistQuestion.value, scan_id: scanId.value },
    )
    assistAnswer.value = res.answer || ''
    assistSources.value = res.sources || []
  } catch (e) {
    assistError.value = `提问失败：${errorMessage(e)}`
  } finally {
    assistLoading.value = false
  }
}

function connectSocket(): void {
  if (!Number.isFinite(scanId.value) || scanId.value <= 0) return
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  socket = new WebSocket(`${proto}://${window.location.host}/ws/scans/${scanId.value}`)
  socket.onmessage = (message) => {
    try {
      const event = JSON.parse(message.data) as LiveEvent
      liveEvents.value.push(event)
      if (liveEvents.value.length > 100) liveEvents.value.shift()
      if (event.event === 'node.start' && event.node) {
        timelineNodes.value.push({ node: event.node, status: 'running', tokens: 0 } as NodeRun)
      }
      if (event.event === 'node.end' && event.node) {
        const existing = timelineNodes.value.find(
          (node) => node.node === event.node && node.status === 'running',
        )
        if (existing) {
          existing.status = event.status || 'ok'
          existing.duration_ms = event.duration_ms
          existing.tokens = event.tokens || 0
        }
      }
    } catch {
      // 忽略非 JSON 消息
    }
  }
}

function normalizeFindings(payload: unknown): GraphFinding[] | null {
  if (Array.isArray(payload)) return payload as GraphFinding[]
  if (payload && typeof payload === 'object') {
    const list = (payload as { findings?: unknown }).findings
    if (Array.isArray(list)) return list as GraphFinding[]
  }
  return null
}

function collectFromGraph(g: GraphResponse | null): GraphFinding[] {
  if (!g?.nodes) return []
  const map = new Map<number, GraphFinding>()
  for (const node of g.nodes) {
    for (const finding of node.findings ?? []) {
      if (finding?.id !== undefined) map.set(finding.id, finding)
    }
  }
  return [...map.values()]
}

function schedulePoll(): void {
  clearPoll()
  if (scan.value?.status === 'running') {
    pollTimer = window.setTimeout(() => void load(true), 5000)
  }
}

function clearPoll(): void {
  if (pollTimer !== undefined) {
    window.clearTimeout(pollTimer)
    pollTimer = undefined
  }
}

async function load(silent = false): Promise<void> {
  clearPoll()
  if (!silent) loading.value = true
  error.value = ''
  notFound.value = false
  findingNote.value = ''
  const id = scanId.value
  if (!Number.isFinite(id) || id <= 0) {
    notFound.value = true
    loading.value = false
    return
  }

  let scanRes: ScanRow
  try {
    scanRes = await api.get<ScanRow>(`/api/scans/${id}`)
    scan.value = scanRes
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      notFound.value = true
      scan.value = null
      loading.value = false
      return
    }
    error.value = `加载扫描失败：${errorMessage(e)}`
    loading.value = false
    return
  }

  const [timelineRes, graphRes, findingsRes] = await Promise.allSettled([
    api.get<{ nodes?: NodeRun[] }>(`/api/scans/${id}/agents/timeline`),
    api.get<GraphResponse>(`/api/scans/${id}/graph`),
    api.get<unknown>(`/api/scans/${id}/findings`),
  ])

  if (timelineRes.status === 'fulfilled' && Array.isArray(timelineRes.value?.nodes)) {
    timelineNodes.value = timelineRes.value.nodes
    timelineSource.value = '来自 /agents/timeline'
  } else if (Array.isArray(scanRes.timeline)) {
    timelineNodes.value = scanRes.timeline
    timelineSource.value = '来自 /scans/:id timeline 字段'
  } else {
    timelineNodes.value = []
    timelineSource.value = '时间线不可用'
  }

  graph.value = graphRes.status === 'fulfilled' ? graphRes.value : null

  const fromApi =
    findingsRes.status === 'fulfilled' ? normalizeFindings(findingsRes.value) : null
  if (fromApi) {
    findings.value = fromApi
    if (!fromApi.length) findingNote.value = 'findings 端点返回空列表'
  } else {
    const fromGraph = collectFromGraph(graph.value)
    findings.value = fromGraph
    findingNote.value = fromGraph.length
      ? 'findings 端点不可用（404/错误），已从 graph 节点聚合 findings'
      : 'findings 端点不可用，且图中的节点没有附带 findings'
  }

  if (!silent) loading.value = false
  void loadArtifacts()
  schedulePoll()
}

async function openFinding(row: GraphFinding): Promise<void> {
  drawer.value = true
  detailLoading.value = true
  selected.value = { ...row }
  sourceLines.value = []
  try {
    const detail = await api.get<FindingDetail>(`/api/findings/${row.id}`)
    selected.value = { ...row, ...detail }
  } catch (e) {
    selected.value = { ...row }
    error.value = `Finding 详情接口失败，展示图中摘要：${errorMessage(e)}`
  }
  const path = (selected.value.file_rel || selected.value.file) as string | undefined
  if (path && selected.value.line) {
    try {
      const source = await api.get<{ lines?: SourceLine[] }>(`/api/scans/${scanId.value}/source`, {
        path,
        start: Math.max(1, Number(selected.value.line) - 25),
        end: Number(selected.value.line) + 25,
      })
      sourceLines.value = source?.lines ?? []
    } catch {
      sourceLines.value = []
    }
  }
  detailLoading.value = false
}

watch(scanId, () => {
  socket?.close()
  void load()
  connectSocket()
})
onMounted(() => {
  void load()
  connectSocket()
})
onUnmounted(() => {
  socket?.close()
  clearPoll()
})
</script>

<style scoped>
.timeline-card {
  border: 1px solid var(--cs-border);
  border-radius: 10px;
  padding: 12px 14px;
  background: #fff;
}

.timeline-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.source-view {
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 10px;
  overflow: auto;
  max-height: 380px;
  padding: 10px 0;
  font-family: 'SFMono-Regular', ui-monospace, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
}

.source-line {
  display: flex;
  gap: 12px;
  padding: 0 12px;
  white-space: pre;
}

.source-line.target {
  background: rgba(250, 204, 21, 0.18);
  border-left: 3px solid #facc15;
  padding-left: 9px;
}

.source-no {
  color: #64748b;
  min-width: 48px;
  text-align: right;
  user-select: none;
}

.source-text {
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
