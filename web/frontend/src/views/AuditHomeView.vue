<template>
  <div>
    <page-header title="Agent 审计" subtitle="Graph Audit Console · Multi-Agent 源码审计入口">
      <template #actions>
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
        <el-button @click="router.push('/dashboard')">仪表盘</el-button>
        <el-button type="primary" @click="router.push('/instant')">即时分析</el-button>
      </template>
    </page-header>

    <error-alert :message="error" @retry="load" />

    <div class="hero-console">
      <div>
        <div class="hero-kicker">DEEPAUDIT × CODESENTRY / LANGGRAPH RUNTIME</div>
        <h1 class="hero-title">导入项目，让 <span>Agent 审计战队</span><br />沿着代码图把漏洞走通。</h1>
        <p class="hero-copy">
          Recon 识别入口 → GraphBuild 建图 → PathAudit 沿 entry→sink 审计 →
          Verification 在沙箱里跑 Harness → Report 输出可追溯证据。
        </p>
        <div class="hero-actions">
          <el-button type="primary" :loading="submitting" @click="pickFile">上传源码审计</el-button>
          <el-button @click="router.push('/scans')">Git / Diff 扫描</el-button>
          <el-button plain @click="router.push('/projects')">项目管理</el-button>
        </div>
        <div class="upload-hint">
          <el-checkbox v-model="oss">标记为 OSS 许可仓库（启用 CodeQL）</el-checkbox>
          <span v-if="pickedName" class="mono">已选择：{{ pickedName }}</span>
        </div>
        <input ref="fileInput" type="file" hidden accept=".zip,.tar,.tar.gz,.tgz" @change="onFile" />
      </div>
      <div class="hero-terminal">
        <div><span class="prompt">$</span> codesentry audit --status</div>
        <div>agents ...... <span class="ok">{{ agents.length }} managed</span></div>
        <div>graph ....... <span class="ok">tree-sitter · 6 languages</span></div>
        <div>engines ..... <span class="ok">semgrep · codeql · joern</span></div>
        <div>runtime ..... <span class="ok">langgraph · supervisor</span></div>
        <div>verification  <span class="warn">harness · docker sandbox</span></div>
        <div><span class="prompt">$</span> tasks: {{ scans.length }} · running: {{ health?.queue?.running_scans ?? 0 }}</div>
        <div v-if="latestScan"><span class="prompt">$</span> latest: #{{ latestScan.id }} {{ latestScan.status }}</div>
      </div>
    </div>

    <div class="stat-grid">
      <div class="stat-card">
        <span class="stat-label">Agent 战队</span>
        <span class="stat-value">{{ agents.filter((a) => a.enabled !== false).length }}</span>
        <span class="stat-hint">managed agents</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">审计任务</span>
        <span class="stat-value">{{ scans.length }}</span>
        <span class="stat-hint">最近 200 条</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">Findings</span>
        <span class="stat-value">{{ dashboard?.findings ?? 0 }}</span>
        <span class="stat-hint">候选 + 已验证</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">Verified</span>
        <span class="stat-value">{{ dashboard?.verified_runs ?? 0 }}</span>
        <span class="stat-hint">Harness 验证通过</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">运行中</span>
        <span class="stat-value">{{ health?.queue?.running_scans ?? 0 }}</span>
        <span class="stat-hint">LangGraph workers</span>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="15">
        <div class="panel">
          <div class="toolbar">
            <h2 class="panel-title" style="margin: 0">最近审计任务</h2>
            <div class="grow" />
            <el-button size="small" @click="router.push('/scans')">全部任务</el-button>
          </div>
          <el-table :data="scans.slice(0, 8)" size="small" row-key="id" @row-click="openScan">
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="repo_path" label="目标" min-width="280" show-overflow-tooltip />
            <el-table-column label="状态" width="100">
              <template #default="{ row }"><status-tag :status="row.status" /></template>
            </el-table-column>
            <el-table-column label="OSS" width="70">
              <template #default="{ row }">{{ row.OSS ? '是' : '否' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="150">
              <template #default="{ row }">
                <el-button link type="primary" @click.stop="openWorkbench(row)">工作台</el-button>
                <el-button link @click.stop="openScan(row)">详情</el-button>
              </template>
            </el-table-column>
            <template #empty><el-empty :image-size="60" description="还没有审计任务，上传源码开始" /></template>
          </el-table>
        </div>
      </el-col>
      <el-col :xs="24" :lg="9">
        <div class="panel">
          <h2 class="panel-title">Agent 战队 <span class="panel-subtitle">配置与启停</span></h2>
          <div class="agent-strip">
            <div v-for="agent in agents" :key="agent.name" class="agent-chip">
              <span class="agent-dot" :class="{ off: agent.enabled === false }" />
              <span class="mono">{{ agent.name }}</span>
              <span class="muted">{{ agent.model_role || 'fast' }}</span>
            </div>
          </div>
          <el-button size="small" @click="router.push('/agents')">管理 Agent</el-button>
        </div>
        <div class="panel">
          <h2 class="panel-title">实时审计流 <span class="panel-subtitle">最近事件</span></h2>
          <div class="mini-stream">
            <div v-for="event in events" :key="event.seq" class="mini-event">
              <el-tag size="small" effect="plain">{{ event.event_type }}</el-tag>
              <span class="mono muted">{{ event.agent || 'system' }}</span>
              <span class="mini-text">{{ summary(event) }}</span>
            </div>
            <el-empty v-if="!events.length" :image-size="50" description="暂无 Agent 事件" />
          </div>
          <el-button v-if="latestScan" size="small" @click="openWorkbench(latestScan)">打开工作台</el-button>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { api, errorMessage } from '@/api/client'
import type { AgentConfig, ScanRow } from '@/api/types'
import ErrorAlert from '@/components/ErrorAlert.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'

interface AgentEvent {
  seq: number
  event_type: string
  agent?: string
  payload?: Record<string, unknown>
}

const router = useRouter()
const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const scans = ref<ScanRow[]>([])
const agents = ref<AgentConfig[]>([])
const health = ref<Record<string, any> | null>(null)
const dashboard = ref<Record<string, any> | null>(null)
const events = ref<AgentEvent[]>([])
const oss = ref(false)
const pickedName = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
let pickedFile: File | null = null

const latestScan = computed(() => scans.value[0] || null)

function summary(event: AgentEvent): string {
  const p = event.payload || {}
  return String(p.reason || p.message || p.node || p.tool || p.status || p.path_id || '')
}

function pickFile(): void {
  fileInput.value?.click()
}

function onFile(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] || null
  pickedFile = file
  pickedName.value = file?.name || ''
  if (file) void submit()
  input.value = ''
}

async function submit(): Promise<void> {
  if (!pickedFile) return
  submitting.value = true
  error.value = ''
  try {
    const form = new FormData()
    form.append('file', pickedFile)
    const res = await api.postForm<{ scan_id: number }>('/api/scans', form, {
      query: { oss: oss.value ? 'true' : 'false' },
    })
    ElMessage.success(`审计任务 #${res.scan_id} 已创建`)
    pickedFile = null
    pickedName.value = ''
    await router.push(`/scans/${res.scan_id}/workbench`)
  } catch (e) {
    error.value = `上传失败：${errorMessage(e)}`
  } finally {
    submitting.value = false
  }
}

function openScan(row: ScanRow): void {
  void router.push(`/scans/${row.id}`)
}

function openWorkbench(row: ScanRow): void {
  void router.push(`/scans/${row.id}/workbench`)
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [s, a, h, d] = await Promise.allSettled([
      api.get<ScanRow[]>('/api/scans'),
      api.get<{ agents?: AgentConfig[] }>('/api/agents'),
      api.get<Record<string, any>>('/api/health'),
      api.get<Record<string, any>>('/api/dashboard'),
    ])
    scans.value = s.status === 'fulfilled' ? s.value : []
    agents.value = a.status === 'fulfilled' ? (a.value.agents || []) : []
    health.value = h.status === 'fulfilled' ? h.value : null
    dashboard.value = d.status === 'fulfilled' ? d.value : null
    if (latestScan.value) {
      try {
        const ev = await api.get<{ events?: AgentEvent[] }>(
          `/api/scans/${latestScan.value.id}/events`,
          { limit: 8 },
        )
        events.value = (ev.events || []).slice(-8).reverse()
      } catch {
        events.value = []
      }
    }
  } catch (e) {
    error.value = `加载失败：${errorMessage(e)}`
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.upload-hint {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin-top: 12px;
  color: var(--cs-muted);
  font-size: 12px;
}
.agent-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}
.agent-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--cs-border);
  border-radius: 4px;
  padding: 5px 7px;
  background: var(--cs-panel-soft);
  font-size: 11px;
}
.agent-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--cs-green);
  box-shadow: 0 0 6px var(--cs-green);
}
.agent-dot.off {
  background: var(--cs-faint);
  box-shadow: none;
}
.mini-stream {
  max-height: 250px;
  overflow: auto;
  margin-bottom: 10px;
}
.mini-event {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 5px 0;
  border-bottom: 1px dashed var(--cs-border);
  font-size: 11px;
}
.mini-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--cs-muted);
}
</style>
