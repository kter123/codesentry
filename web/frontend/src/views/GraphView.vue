<template>
  <div>
    <page-header :title="`代码图 · 扫描 #${scanId}`" subtitle="节点、调用链、污点边与接口资产">
      <template #actions>
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
        <el-button @click="goScan">返回扫描</el-button>
      </template>
    </page-header>

    <error-alert :message="error" @retry="load" />

    <div class="panel graph-toolbar">
      <el-select v-model="kindFilter" multiple collapse-tags placeholder="节点类型" style="width: 260px">
        <el-option v-for="kind in kinds" :key="kind" :label="kind" :value="kind" />
      </el-select>
      <el-input v-model="search" placeholder="搜索节点 / 文件" clearable style="width: 220px" />
      <el-checkbox v-model="onlyFindings">仅显示 finding 相关</el-checkbox>
      <el-checkbox v-model="onlyTaint">仅显示污点边</el-checkbox>
      <span class="muted">
        {{ visibleNodes.length }} / {{ graph?.nodes?.length ?? 0 }} 节点 ·
        {{ visibleEdges.length }} 边 · 构建 #{{ graph?.graph_build_id ?? '—' }}
      </span>
    </div>

    <el-alert
      v-if="truncated"
      type="warning"
      :closable="false"
      show-icon
      title="节点过多，仅渲染前 800 个；请用过滤条件缩小范围。"
      style="margin-bottom: 12px"
    />

    <el-row :gutter="16">
      <el-col :xs="24" :lg="17">
        <div class="panel">
          <div ref="chartEl" class="graph-canvas" />
          <el-empty v-if="!visibleNodes.length" description="没有匹配的图节点" :image-size="70" />
        </div>
      </el-col>
      <el-col :xs="24" :lg="7">
        <div class="panel">
          <h2 class="panel-title">接口资产</h2>
          <el-table :data="graph?.endpoints || []" size="small" max-height="300">
            <el-table-column prop="permission" label="权限" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="permissionType(row.permission)">{{ row.permission }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="method" label="方法" width="70" />
            <el-table-column prop="route" label="路径" min-width="140" show-overflow-tooltip />
            <el-table-column prop="evidence" label="依据" min-width="120" show-overflow-tooltip />
            <template #empty><el-empty :image-size="46" description="未登记接口" /></template>
          </el-table>
        </div>

        <div class="panel">
          <h2 class="panel-title">节点详情</h2>
          <template v-if="selected">
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="Key"><span class="mono">{{ selected.key }}</span></el-descriptions-item>
              <el-descriptions-item label="类型">{{ selected.kind }}</el-descriptions-item>
              <el-descriptions-item label="名称">{{ selected.qualified_name || selected.name }}</el-descriptions-item>
              <el-descriptions-item label="位置">{{ selected.file }}:{{ selected.start }}</el-descriptions-item>
            </el-descriptions>
            <div class="toolbar" style="margin-top: 8px">
              <el-tag v-for="n in neighbors" :key="n.key" size="small" effect="plain" style="cursor: pointer" @click="focusNode(n.key)">
                {{ n.kind }} · {{ n.name || n.key }}
              </el-tag>
            </div>
            <el-table v-if="selected.findings?.length" :data="selected.findings" size="small" style="margin-top: 10px">
              <el-table-column prop="rule_id" label="规则" width="110" />
              <el-table-column prop="severity" label="级别" width="70" />
              <el-table-column prop="message" label="说明" min-width="150" show-overflow-tooltip />
            </el-table>
            <pre v-if="sourceSnippet" class="pre-block" style="margin-top: 10px">{{ sourceSnippet }}</pre>
          </template>
          <el-empty v-else :image-size="50" description="点击图中节点查看详情" />
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'
import { Refresh } from '@element-plus/icons-vue'

import { api, errorMessage } from '@/api/client'
import ErrorAlert from '@/components/ErrorAlert.vue'
import PageHeader from '@/components/PageHeader.vue'

interface GraphNode {
  id: string
  key: string
  kind: string
  name: string
  file?: string
  qualified_name?: string
  start?: number
  end?: number
  lang?: string
  findings?: Array<Record<string, unknown>>
}

interface GraphEdge {
  source: string
  target: string
  kind: string
  provenance?: string
  confidence?: number
}

interface GraphPayload {
  scan_id: number
  mode?: string
  languages?: string[]
  graph_build_id?: number | null
  nodes?: GraphNode[]
  edges?: GraphEdge[]
  endpoints?: Array<Record<string, string | number | boolean>>
}

const route = useRoute()
const router = useRouter()
const scanId = computed(() => Number(route.params.id || 0))
const loading = ref(false)
const error = ref('')
const graph = ref<GraphPayload | null>(null)
const chartEl = ref<HTMLDivElement | null>(null)
const chart = ref<echarts.ECharts | null>(null)
const kindFilter = ref<string[]>([])
const search = ref('')
const onlyFindings = ref(false)
const onlyTaint = ref(false)
const selectedKey = ref('')
const neighbors = ref<GraphNode[]>([])
const sourceSnippet = ref('')
const truncated = ref(false)

const KIND_COLORS: Record<string, string> = {
  repo: '#334155', package: '#64748b', file: '#94a3b8', class: '#7c3aed',
  function: '#2563eb', method: '#0ea5e9', route: '#f59e0b', endpoint: '#ef4444',
  source: '#10b981', sink: '#dc2626', external: '#a8a29e', module: '#a8a29e',
}
const EDGE_COLORS: Record<string, string> = {
  contains: '#cbd5e1', imports: '#94a3b8', calls: '#2563eb',
  routes_to: '#f59e0b', exposes: '#ef4444', taints_to: '#dc2626',
}

const kinds = computed(() => {
  const set = new Set<string>()
  for (const node of graph.value?.nodes || []) set.add(node.kind)
  return [...set].sort()
})

const selected = computed(() =>
  (graph.value?.nodes || []).find((n) => n.key === selectedKey.value) || null,
)

function nodeMatches(node: GraphNode): boolean {
  if (kindFilter.value.length && !kindFilter.value.includes(node.kind)) return false
  if (search.value.trim()) {
    const q = search.value.trim().toLowerCase()
    const text = `${node.name} ${node.qualified_name || ''} ${node.file || ''}`.toLowerCase()
    if (!text.includes(q)) return false
  }
  if (onlyFindings.value && !(node.findings?.length)) return false
  return true
}

const visibleNodes = computed(() => (graph.value?.nodes || []).filter(nodeMatches).slice(0, 800))
const visibleIds = computed(() => new Set(visibleNodes.value.map((n) => n.key)))
const visibleEdges = computed(() =>
  (graph.value?.edges || []).filter(
    (e) => visibleIds.value.has(e.source) && visibleIds.value.has(e.target)
      && (!onlyTaint.value || e.kind === 'taints_to'),
  ),
)

function render(): void {
  if (!chartEl.value) return
  if (!chart.value) chart.value = echarts.init(chartEl.value, undefined, { renderer: 'canvas' })
  truncated.value = (graph.value?.nodes?.length || 0) > 800 && visibleNodes.value.length >= 800
  const categories = kinds.value.map((kind) => ({ name: kind }))
  const categoryIndex = new Map(kinds.value.map((kind, index) => [kind, index]))
  const option: EChartsOption = {
    tooltip: {
      formatter: (params: any) => {
        if (params.dataType === 'edge') return `${params.data.kind}`
        const data = params.data || {}
        return `${data.kind} · ${data.qualified_name || data.name || data.id}<br/>${data.file || ''}`
      },
    },
    legend: { data: categories.map((c) => c.name), bottom: 0, textStyle: { color: '#64748b' } },
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        animation: false,
        force: { repulsion: 80, edgeLength: [30, 90], gravity: 0.1 },
        label: {
          show: visibleNodes.value.length <= 300,
          fontSize: 10,
          formatter: (p: any) => String(p.name || '').slice(0, 20),
        },
        lineStyle: { opacity: 0.55, curveness: 0.08 },
        emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
        categories,
        data: visibleNodes.value.map((node) => ({
          id: node.key,
          key: node.key,
          name: node.name || node.key,
          category: categoryIndex.get(node.kind) ?? 0,
          kind: node.kind,
          qualified_name: node.qualified_name,
          file: node.file,
          symbolSize: node.kind === 'endpoint' ? 16 : node.findings?.length ? 18 : 10,
          itemStyle: { color: KIND_COLORS[node.kind] || '#64748b' },
        })),
        links: visibleEdges.value.map((edge) => ({
          source: edge.source,
          target: edge.target,
          kind: edge.kind,
          lineStyle: { color: EDGE_COLORS[edge.kind] || '#cbd5e1' },
        })),
      },
    ],
  }
  chart.value.setOption(option, true)
  chart.value.off('click')
  chart.value.on('click', (params: any) => {
    if (params.dataType === 'node' && params.data?.key) void focusNode(params.data.key)
  })
  chart.value.resize()
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    graph.value = await api.get<GraphPayload>(
      `/api/scans/${scanId.value}/graph`,
      { limit: 800 },
    )
    if (!kindFilter.value.length) kindFilter.value = kinds.value
    render()
  } catch (e) {
    error.value = `加载代码图失败：${errorMessage(e)}`
  } finally {
    loading.value = false
  }
}

async function focusNode(key: string): Promise<void> {
  selectedKey.value = key
  sourceSnippet.value = ''
  neighbors.value = []
  try {
    const res = await api.get<{ node: GraphNode; neighbors?: { nodes?: GraphNode[] } }>(
      `/api/scans/${scanId.value}/graph/node/${encodeURIComponent(key)}`,
    )
    neighbors.value = res.neighbors?.nodes || []
    const node = res.node
    if (node?.file) {
      const src = await api.get<{ lines?: Array<{ no: number; text: string }> }>(
        `/api/scans/${scanId.value}/source`,
        { path: node.file, start: node.start || 1, end: node.end || (node.start || 1) + 80 },
      )
      sourceSnippet.value = (src.lines || []).map((l) => `${l.no}: ${l.text}`).join('\n')
    }
  } catch {
    neighbors.value = []
  }
}

function permissionType(permission: string): 'danger' | 'warning' | 'success' | 'info' {
  if (permission === '内部接口' || permission === '公开') return 'danger'
  if (permission === '管理员权限') return 'warning'
  if (permission === '登录用户' || permission === '注册用户') return 'success'
  return 'info'
}

function goScan(): void {
  void router.push(`/scans/${scanId.value}`)
}

watch([kindFilter, search, onlyFindings, onlyTaint], () => render(), { deep: true })

onMounted(() => {
  void load()
})
onUnmounted(() => {
  chart.value?.dispose()
  chart.value = null
})
</script>

<style scoped>
.graph-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.graph-canvas {
  width: 100%;
  height: 620px;
}
</style>
