<template>
  <div>
    <page-header
      title="Agent 管理"
      subtitle="编排/验证节点的启停、模型绑定与能力边界"
    >
      <template #actions>
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
      </template>
    </page-header>

    <error-alert :message="error" @retry="load" />

    <div v-loading="loading">
      <div v-if="agents.length" class="agent-grid">
        <el-card v-for="agent in agents" :key="agent.name" shadow="never" class="agent-card">
          <div class="agent-card-head">
            <div>
              <div class="agent-name">{{ agent.display_name || agent.name }}</div>
              <div class="mono muted">{{ agent.name }}</div>
            </div>
            <el-switch
              :model-value="agent.enabled !== false"
              :loading="saving[agent.name] === true"
              @change="(value: boolean) => toggle(agent, value)"
            />
          </div>

          <div class="inline-tags" style="margin: 12px 0">
            <el-tag size="small" :type="agent.enabled !== false ? 'success' : 'info'">
              {{ agent.enabled !== false ? '启用' : '停用' }}
            </el-tag>
            <el-tag size="small" effect="plain">{{ agent.model_role || 'fast' }}</el-tag>
            <el-tag size="small" effect="plain">{{ profileName(agent.llm_profile_id) }}</el-tag>
            <el-tag size="small" :type="agent.prompt_version ? 'success' : 'warning'" effect="plain">
              Prompt {{ agent.prompt_version ? `v${agent.prompt_version}` : 'seed' }}
            </el-tag>
          </div>

          <div class="muted" style="font-size: 12px; line-height: 1.7">
            <div>超时：{{ agent.timeout_s ?? '—' }} s · 最大迭代：{{ agent.max_iterations ?? '—' }}</div>
            <div>
              能力：
              <span v-if="agent.capabilities?.network">network </span>
              <span v-if="agent.capabilities?.shell">shell </span>
              <span v-if="agent.capabilities?.poc_exec">poc_exec </span>
              <span v-if="agent.capabilities?.engines?.length">
                engines: {{ agent.capabilities.engines.join(', ') }}
              </span>
              <span
                v-if="
                  !agent.capabilities?.network &&
                  !agent.capabilities?.shell &&
                  !agent.capabilities?.poc_exec &&
                  !agent.capabilities?.engines?.length
                "
              >
                无
              </span>
            </div>
          </div>

          <div class="agent-card-actions">
            <el-button size="small" type="primary" plain @click="$router.push(`/agents/${agent.name}`)">
              配置
            </el-button>
            <el-button size="small" @click="$router.push(`/agents/${agent.name}`)">
              Prompt / 配置
            </el-button>
            <el-button size="small" @click="$router.push('/skills')">Skills</el-button>
          </div>
        </el-card>
      </div>
      <el-empty
        v-else-if="!loading && !error"
        :image-size="80"
        description="没有可用的 Agent 配置"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { api, errorMessage } from '@/api/client'
import type { AgentConfig, LlmProfile } from '@/api/types'
import ErrorAlert from '@/components/ErrorAlert.vue'
import PageHeader from '@/components/PageHeader.vue'

const loading = ref(false)
const error = ref('')
const agents = ref<AgentConfig[]>([])
const profiles = ref<LlmProfile[]>([])
const saving = reactive<Record<string, boolean>>({})

function profileName(id?: number | null): string {
  if (!id) return '全局默认 LLM'
  const profile = profiles.value.find((p) => p.id === id)
  return profile ? profile.name : `Profile #${id}`
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  const [agentsRes, profilesRes] = await Promise.allSettled([
    api.get<{ agents: AgentConfig[] }>('/api/agents'),
    api.get<{ profiles: LlmProfile[] }>('/api/llm-profiles'),
  ])
  if (agentsRes.status === 'fulfilled') {
    agents.value = agentsRes.value?.agents ?? []
  } else {
    error.value = `加载 Agent 失败：${errorMessage(agentsRes.reason)}`
  }
  if (profilesRes.status === 'fulfilled') {
    profiles.value = profilesRes.value?.profiles ?? []
  }
  loading.value = false
}

async function toggle(agent: AgentConfig, enabled: boolean): Promise<void> {
  saving[agent.name] = true
  try {
    await api.put(`/api/agents/${agent.name}`, { enabled })
    agent.enabled = enabled
    ElMessage.success(`${agent.display_name || agent.name} 已${enabled ? '启用' : '停用'}`)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    saving[agent.name] = false
  }
}

onMounted(load)
</script>

<style scoped>
.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.agent-card {
  border-radius: 12px;
}

.agent-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.agent-name {
  font-size: 16px;
  font-weight: 650;
}

.agent-card-actions {
  display: flex;
  gap: 8px;
  margin-top: 14px;
  flex-wrap: wrap;
}
</style>
