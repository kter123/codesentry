<template>
  <div>
    <page-header title="用量与配额" subtitle="LLM 调用、Token、成本聚合与月度硬预算">
      <template #actions>
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
        <el-button @click="quotaDialog = true">调整配额</el-button>
      </template>
    </page-header>

    <error-alert :message="error" @retry="load" />

    <div class="stat-grid">
      <div class="stat-card">
        <span class="stat-label">总调用</span>
        <span class="stat-value">{{ totals.calls.toLocaleString() }}</span>
        <span class="stat-hint">成功率 {{ totals.successRate }}%</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">总 Tokens</span>
        <span class="stat-value">{{ totals.tokens.toLocaleString() }}</span>
        <span class="stat-hint">
          prompt {{ totals.promptTokens.toLocaleString() }} / completion
          {{ totals.completionTokens.toLocaleString() }}
        </span>
      </div>
      <div class="stat-card">
        <span class="stat-label">总成本</span>
        <span class="stat-value">${{ totals.cost.toFixed(4) }}</span>
        <span class="stat-hint">来自 llm_usage 台账</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">月配额</span>
        <span class="stat-value">{{ quota?.tokens_limit ? `${quota.tokens_pct}%` : '未设置' }}</span>
        <span class="stat-hint">
          {{ (quota?.tokens_used ?? 0).toLocaleString() }} /
          {{ quota?.tokens_limit ? quota.tokens_limit.toLocaleString() : '∞' }} tokens
        </span>
      </div>
    </div>

    <div class="panel">
      <h2 class="panel-title">月度配额</h2>
      <template v-if="quota">
        <div class="quota-row">
          <span>Tokens</span>
          <el-progress
            :percentage="Math.min(100, quota.tokens_pct || 0)"
            :status="quota.warn ? 'warning' : undefined"
            :stroke-width="14"
          />
          <span class="mono muted">
            {{ (quota.tokens_used || 0).toLocaleString() }} /
            {{ quota.tokens_limit ? quota.tokens_limit.toLocaleString() : '∞' }}
          </span>
        </div>
        <div class="quota-row">
          <span>USD</span>
          <el-progress
            :percentage="Math.min(100, quota.usd_pct || 0)"
            :status="quota.warn ? 'warning' : undefined"
            :stroke-width="14"
          />
          <span class="mono muted">
            ${{ Number(quota.usd_used || 0).toFixed(4) }} /
            {{ quota.usd_limit ? `$${Number(quota.usd_limit).toFixed(2)}` : '∞' }}
          </span>
        </div>
        <el-alert
          v-if="quota.warn"
          type="warning"
          show-icon
          :closable="false"
          title="用量已达到配额的 80% 以上，请关注预算消耗。"
          style="margin-top: 10px"
        />
      </template>
      <el-empty v-else :image-size="56" description="配额信息不可用" />
    </div>

    <div class="panel">
      <div class="toolbar">
        <el-radio-group v-model="groupBy" @change="loadSummary">
          <el-radio-button value="agent">按 Agent</el-radio-button>
          <el-radio-button value="profile">按 Profile</el-radio-button>
          <el-radio-button value="scan">按扫描</el-radio-button>
          <el-radio-button value="day">按天</el-radio-button>
        </el-radio-group>
        <el-date-picker
          v-model="range"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          style="width: 260px"
          @change="loadSummary"
        />
        <div class="grow" />
        <el-select v-model="metric" style="width: 150px">
          <el-option label="Tokens" value="tokens" />
          <el-option label="成本 (USD)" value="cost_usd" />
          <el-option label="调用次数" value="calls" />
        </el-select>
      </div>

      <usage-chart :rows="rows" :metric="metric" />

      <el-table v-loading="loading" :data="rows" size="small" max-height="420" style="margin-top: 12px">
        <el-table-column prop="key" :label="keyLabel" min-width="140" show-overflow-tooltip />
        <el-table-column prop="calls" label="调用" width="90" />
        <el-table-column prop="prompt_tokens" label="Prompt" width="110" />
        <el-table-column prop="completion_tokens" label="Completion" width="120" />
        <el-table-column prop="tokens" label="Tokens" width="110" />
        <el-table-column label="成本" width="110">
          <template #default="{ row }">${{ Number(row.cost_usd || 0).toFixed(4) }}</template>
        </el-table-column>
        <el-table-column prop="avg_latency_ms" label="平均延迟" width="110" />
        <el-table-column label="成功率" width="100">
          <template #default="{ row }">
            {{ row.calls ? ((row.ok_calls / row.calls) * 100).toFixed(1) : '0.0' }}%
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :image-size="70" description="所选区间没有 LLM 用量记录" />
        </template>
      </el-table>
    </div>

    <el-dialog v-model="quotaDialog" title="调整月度配额" width="430px">
      <el-alert
        v-if="quotaError"
        type="error"
        :title="quotaError"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      />
      <el-form label-position="top">
        <el-form-item label="Token 上限（0 表示不限制）">
          <el-input-number v-model="quotaForm.tokens" :min="0" :step="10000" style="width: 100%" />
        </el-form-item>
        <el-form-item label="USD 上限（0 表示不限制）">
          <el-input-number v-model="quotaForm.usd" :min="0" :step="1" :precision="2" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="quotaDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingQuota" @click="saveQuota">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { api, errorMessage } from '@/api/client'
import type { UsageRow } from '@/api/types'
import ErrorAlert from '@/components/ErrorAlert.vue'
import PageHeader from '@/components/PageHeader.vue'
import UsageChart from '@/components/UsageChart.vue'

interface Quota {
  period?: string
  tokens_used?: number
  usd_used?: number
  tokens_limit?: number
  usd_limit?: number
  tokens_pct?: number
  usd_pct?: number
  warn?: boolean
}

const loading = ref(false)
const error = ref('')
const rows = ref<UsageRow[]>([])
const groupBy = ref<'agent' | 'profile' | 'scan' | 'day'>('agent')
const metric = ref<'tokens' | 'cost_usd' | 'calls'>('tokens')
const range = ref<[string, string] | null>(null)
const quota = ref<Quota | null>(null)

const quotaDialog = ref(false)
const quotaError = ref('')
const savingQuota = ref(false)
const quotaForm = reactive({ tokens: 0, usd: 0 })

const keyLabel = computed(() => {
  const map: Record<string, string> = {
    agent: 'Agent',
    profile: 'Profile ID',
    scan: '扫描 ID',
    day: '日期',
  }
  return map[groupBy.value] ?? '分组'
})

const totals = computed(() => {
  const acc = {
    calls: 0,
    tokens: 0,
    promptTokens: 0,
    completionTokens: 0,
    cost: 0,
    okCalls: 0,
    successRate: '0.0',
  }
  for (const row of rows.value) {
    acc.calls += Number(row.calls || 0)
    acc.tokens += Number(row.tokens || 0)
    acc.promptTokens += Number(row.prompt_tokens || 0)
    acc.completionTokens += Number(row.completion_tokens || 0)
    acc.cost += Number(row.cost_usd || 0)
    acc.okCalls += Number(row.ok_calls || 0)
  }
  acc.successRate = acc.calls ? ((acc.okCalls / acc.calls) * 100).toFixed(1) : '0.0'
  return acc
})

async function loadSummary(): Promise<void> {
  loading.value = true
  error.value = ''
  const query: Record<string, string> = { group_by: groupBy.value }
  if (range.value?.[0]) query.from = range.value[0]
  if (range.value?.[1]) query.to = `${range.value[1]}T23:59:59`
  try {
    const res = await api.get<{ group_by: string; rows: UsageRow[] }>('/api/usage/summary', query)
    rows.value = res?.rows ?? []
  } catch (e) {
    error.value = `加载用量失败：${errorMessage(e)}`
  } finally {
    loading.value = false
  }
}

async function loadQuota(): Promise<void> {
  try {
    const res = await api.get<Quota>('/api/usage/quota')
    quota.value = res
    quotaForm.tokens = Number(res.tokens_limit || 0)
    quotaForm.usd = Number(res.usd_limit || 0)
  } catch {
    quota.value = null
  }
}

async function load(): Promise<void> {
  await Promise.all([loadSummary(), loadQuota()])
}

async function saveQuota(): Promise<void> {
  quotaError.value = ''
  savingQuota.value = true
  try {
    const res = await api.put<Quota>('/api/usage/quota', {
      tokens: quotaForm.tokens,
      usd: quotaForm.usd,
    })
    quota.value = res
    quotaDialog.value = false
    ElMessage.success('配额已更新')
  } catch (e) {
    quotaError.value = errorMessage(e)
  } finally {
    savingQuota.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.quota-row {
  display: grid;
  grid-template-columns: 70px 1fr 220px;
  gap: 14px;
  align-items: center;
  margin-bottom: 12px;
}

@media (max-width: 720px) {
  .quota-row {
    grid-template-columns: 1fr;
    gap: 6px;
  }
}
</style>
