<template>
  <div>
    <page-header title="概览" subtitle="扫描运行状态、复核队列与 LLM 用量的统一视图">
      <template #actions>
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
        <el-button type="primary" @click="$router.push('/scans')">新建扫描</el-button>
      </template>
    </page-header>

    <div class="stat-grid">
      <div class="stat-card">
        <span class="stat-label">数据库</span>
        <span class="stat-value">
          <el-tag v-if="health" :type="health.db?.ok ? 'success' : 'danger'" size="small">
            {{ health.db?.ok ? '连接正常' : '不可用' }}
          </el-tag>
          <span v-else class="muted">—</span>
        </span>
        <span class="stat-hint">
          {{ health?.db?.ok ? `延迟 ${health.db.latency_ms ?? 0} ms` : '检查 DB 连接与迁移' }}
        </span>
      </div>
      <div class="stat-card">
        <span class="stat-label">运行中扫描</span>
        <span class="stat-value">{{ health?.queue?.running_scans ?? 0 }}</span>
        <span class="stat-hint">来自 /api/health 队列统计</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">LLM Profiles</span>
        <span class="stat-value">{{ health?.profiles?.count ?? 0 }}</span>
        <span class="stat-hint">
          Docker：{{ health?.docker?.ok ? `可用 ${health.docker.version || ''}` : '不可用' }}
        </span>
      </div>
      <div class="stat-card">
        <span class="stat-label">待复核</span>
        <span class="stat-value">{{ reviews.length }}</span>
        <span class="stat-hint">
          <el-link type="primary" :underline="false" @click="$router.push('/reviews')">
            进入复核队列
          </el-link>
        </span>
      </div>
      <div class="stat-card">
        <span class="stat-label">扫描总数</span>
        <span class="stat-value">{{ scans.length }}</span>
        <span class="stat-hint">最近 200 条中的展示数量</span>
      </div>
    </div>

    <error-alert :message="errorText" @retry="load" />

    <div class="panel">
      <h2 class="panel-title">
        引擎状态 <span class="panel-subtitle">semgrep / codeql / joern</span>
      </h2>
      <div v-if="health" class="inline-tags">
        <el-tag
          v-for="(path, name) in health.engines || {}"
          :key="name"
          :type="path ? 'success' : 'info'"
          effect="plain"
        >
          {{ name }}：{{ path ? '已安装' : '未检测到' }}
        </el-tag>
      </div>
      <el-empty v-else :image-size="60" description="暂无引擎信息" />
    </div>

    <div class="panel">
      <h2 class="panel-title">
        最近扫描
        <span class="panel-subtitle">点击行查看时间线与 findings</span>
      </h2>
      <error-alert :message="sectionErrors.scans" @retry="load" />
      <el-table
        v-if="scans.length"
        v-loading="loading"
        :data="scans.slice(0, 8)"
        size="small"
        row-key="id"
        @row-click="openScan"
      >
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="repo_path" label="仓库" min-width="240" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }">
            <status-tag :status="row.status" />
          </template>
        </el-table-column>
        <el-table-column prop="mode" label="模式" width="90" />
        <el-table-column label="OSS" width="80">
          <template #default="{ row }">{{ row.OSS ? '是' : '否' }}</template>
        </el-table-column>
      </el-table>
      <el-empty
        v-else-if="!loading && !sectionErrors.scans"
        class="section-empty"
        :image-size="70"
        description="还没有扫描记录，前往扫描管理上传代码或 Git 仓库"
      >
        <el-button type="primary" @click="$router.push('/scans')">开始扫描</el-button>
      </el-empty>
    </div>

    <el-row :gutter="18">
      <el-col :xs="24" :lg="12">
        <div class="panel">
          <h2 class="panel-title">复核队列</h2>
          <error-alert :message="sectionErrors.reviews" @retry="load" />
          <el-table v-if="reviews.length" :data="reviews.slice(0, 6)" size="small">
            <el-table-column prop="id" label="扫描" width="70" />
            <el-table-column prop="repo_path" label="仓库" min-width="160" show-overflow-tooltip />
            <el-table-column label="状态" width="110">
              <template #default="{ row }"><status-tag :status="row.status" /></template>
            </el-table-column>
          </el-table>
          <el-empty
            v-else-if="!loading && !sectionErrors.reviews"
            :image-size="60"
            description="没有等待人工复核的扫描"
          />
        </div>
      </el-col>
      <el-col :xs="24" :lg="12">
        <div class="panel">
          <h2 class="panel-title">
            Agent 用量 <span class="panel-subtitle">按 agent 聚合</span>
          </h2>
          <error-alert :message="sectionErrors.usage" @retry="load" />
          <el-table v-if="usage.length" :data="usage.slice(0, 6)" size="small">
            <el-table-column prop="key" label="Agent" min-width="100" />
            <el-table-column prop="calls" label="调用" width="70" />
            <el-table-column prop="tokens" label="Tokens" width="100" />
            <el-table-column label="成本" width="110">
              <template #default="{ row }">${{ Number(row.cost_usd || 0).toFixed(4) }}</template>
            </el-table-column>
          </el-table>
          <el-empty
            v-else-if="!loading && !sectionErrors.usage"
            :image-size="60"
            description="暂无 LLM 调用记录"
          />
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'

import { api, errorMessage } from '@/api/client'
import type { ScanRow, UsageRow } from '@/api/types'
import ErrorAlert from '@/components/ErrorAlert.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'

interface Health {
  db?: { ok?: boolean; latency_ms?: number }
  profiles?: { count?: number }
  docker?: { ok?: boolean; version?: string }
  engines?: Record<string, string>
  queue?: { running_scans?: number }
}

interface ReviewRow {
  id: number
  repo_path: string
  status: string
  created?: string
}

const router = useRouter()
const loading = ref(false)
const health = ref<Health | null>(null)
const scans = ref<ScanRow[]>([])
const reviews = ref<ReviewRow[]>([])
const usage = ref<UsageRow[]>([])
const sectionErrors = reactive<Record<'health' | 'scans' | 'reviews' | 'usage', string>>({
  health: '',
  scans: '',
  reviews: '',
  usage: '',
})

const errorText = computed(() => sectionErrors.health)

function openScan(row: ScanRow): void {
  void router.push(`/scans/${row.id}`)
}

async function load(): Promise<void> {
  loading.value = true
  for (const key of Object.keys(sectionErrors) as Array<keyof typeof sectionErrors>) {
    sectionErrors[key] = ''
  }
  const [h, s, r, u] = await Promise.allSettled([
    api.get<Health>('/api/health'),
    api.get<ScanRow[]>('/api/scans'),
    api.get<{ queue: ReviewRow[] }>('/api/reviews'),
    api.get<{ rows: UsageRow[] }>('/api/usage/summary', { group_by: 'agent' }),
  ])
  if (h.status === 'fulfilled') health.value = h.value
  else sectionErrors.health = `健康检查失败：${errorMessage(h.reason)}`
  if (s.status === 'fulfilled') scans.value = Array.isArray(s.value) ? s.value : []
  else sectionErrors.scans = `扫描列表加载失败：${errorMessage(s.reason)}`
  if (r.status === 'fulfilled') reviews.value = r.value?.queue ?? []
  else sectionErrors.reviews = `复核队列加载失败：${errorMessage(r.reason)}`
  if (u.status === 'fulfilled') usage.value = u.value?.rows ?? []
  else sectionErrors.usage = `用量加载失败：${errorMessage(u.reason)}`
  loading.value = false
}

onMounted(load)
</script>
