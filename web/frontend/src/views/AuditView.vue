<template>
  <div>
    <page-header title="配置审计" subtitle="LLM / Agent / Prompt / Skills / 用户等配置变更的审计日志">
      <template #actions>
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
      </template>
    </page-header>

    <div class="panel">
      <div class="toolbar">
        <el-input v-model="filters.actor" placeholder="操作者" clearable style="width: 180px" @keyup.enter="load" />
        <el-input v-model="filters.target_type" placeholder="目标类型（如 agent_config）" clearable style="width: 230px" @keyup.enter="load" />
        <el-input-number v-model="filters.limit" :min="1" :max="500" :step="50" />
        <el-button type="primary" :loading="loading" @click="load">查询</el-button>
      </div>

      <error-alert :message="error" @retry="load" />
      <el-table v-loading="loading" :data="rows" row-key="id" size="small">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="audit-expand">
              <div>
                <div class="muted" style="margin-bottom: 4px">before</div>
                <json-block :value="row.before" light />
              </div>
              <div>
                <div class="muted" style="margin-bottom: 4px">after</div>
                <json-block :value="row.after" light />
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="created_at" label="时间" min-width="180" show-overflow-tooltip />
        <el-table-column prop="actor" label="操作者" width="130" show-overflow-tooltip />
        <el-table-column prop="action" label="动作" width="110" />
        <el-table-column prop="target_type" label="目标类型" width="150" show-overflow-tooltip />
        <el-table-column prop="target_id" label="目标 ID" min-width="160" show-overflow-tooltip />
        <template #empty>
          <el-empty :image-size="80" description="没有匹配的审计记录" />
        </template>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'

import { api, errorMessage } from '@/api/client'
import type { AuditRow } from '@/api/types'
import ErrorAlert from '@/components/ErrorAlert.vue'
import JsonBlock from '@/components/JsonBlock.vue'
import PageHeader from '@/components/PageHeader.vue'

const loading = ref(false)
const error = ref('')
const rows = ref<AuditRow[]>([])
const filters = reactive({
  actor: '',
  target_type: '',
  limit: 100,
})

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const res = await api.get<{ rows: AuditRow[] }>('/api/audit', {
      limit: filters.limit,
      actor: filters.actor.trim() || undefined,
      target_type: filters.target_type.trim() || undefined,
    })
    rows.value = res?.rows ?? []
  } catch (e) {
    error.value = `加载审计日志失败：${errorMessage(e)}`
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.audit-expand {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  padding: 4px 12px 12px;
}

@media (max-width: 900px) {
  .audit-expand {
    grid-template-columns: 1fr;
  }
}
</style>
