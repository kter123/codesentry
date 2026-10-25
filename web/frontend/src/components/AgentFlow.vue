<template>
  <div class="panel agent-flow-panel">
    <div class="toolbar" style="margin-bottom: 8px">
      <h3 class="panel-title" style="margin: 0">Agent 分析拓扑</h3>
      <span class="panel-subtitle">点击阶段过滤事件 · 状态来自 agent_nodes</span>
      <div class="grow" />
      <span class="muted mono">{{ runningCount }} running / {{ nodes.length }} nodes</span>
    </div>
    <div class="agent-flow">
      <template v-for="(stage, index) in stages" :key="stage.key">
        <button
          class="flow-stage"
          :class="[stage.status, { active: selected === stage.key }]"
          type="button"
          @click="$emit('select', stage.key)"
        >
          <span class="flow-kicker">{{ stage.group }}</span>
          <span class="flow-name">{{ stage.label }}</span>
          <span class="flow-meta">
            <span class="status-dot" />
            {{ stage.status }}
            <template v-if="stage.count"> · {{ stage.count }}x</template>
            <template v-if="stage.tokens"> · {{ stage.tokens }} tok</template>
          </span>
        </button>
        <span v-if="index < stages.length - 1" class="flow-arrow">→</span>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface AgentNode {
  agent_key: string
  name: string
  status?: string
  tokens?: number
}

const props = defineProps<{ nodes: AgentNode[]; selected?: string }>()
defineEmits<{ select: [key: string] }>()

const spec = [
  { key: 'recon', label: 'Recon', group: 'prepare' },
  { key: 'graph_build', label: 'GraphBuild', group: 'graph' },
  { key: 'scan', label: 'Engine Scan', group: 'engine' },
  { key: 'path_build', label: 'PathBuild', group: 'path' },
  { key: 'supervisor', label: 'Supervisor', group: 'orchestrate' },
  { key: 'audit_path', label: 'PathAudit', group: 'audit' },
  { key: 'verification', label: 'Harness Verify', group: 'verify' },
  { key: 'triage', label: 'Triage', group: 'decision' },
  { key: 'deploy', label: 'Deploy', group: 'deliver' },
  { key: 'poc_gen', label: 'PoC', group: 'deliver' },
  { key: 'report', label: 'Report', group: 'output' },
]

const stages = computed(() =>
  spec.map((item) => {
    const matched = props.nodes.filter((n) => n.name === item.key)
    let status = 'idle'
    if (matched.some((n) => n.status === 'failed')) status = 'failed'
    else if (matched.some((n) => n.status === 'running')) status = 'running'
    else if (matched.some((n) => n.status === 'ok')) status = 'ok'
    else if (matched.some((n) => n.status === 'skipped')) status = 'skipped'
    return {
      ...item,
      status,
      count: matched.length,
      tokens: matched.reduce((sum, n) => sum + Number(n.tokens || 0), 0),
    }
  }),
)
const runningCount = computed(() => props.nodes.filter((n) => n.status === 'running').length)
</script>

<style scoped>
.agent-flow-panel {
  padding: 14px 16px;
}
.agent-flow {
  display: flex;
  align-items: stretch;
  gap: 6px;
  overflow-x: auto;
  padding-bottom: 4px;
}
.flow-stage {
  min-width: 122px;
  flex: 1 0 122px;
  border: 1px solid var(--cs-border);
  border-radius: 5px;
  background: var(--cs-panel-soft);
  padding: 8px 10px;
  text-align: left;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 3px;
  color: var(--cs-text);
  transition: all 0.15s ease;
}
.flow-stage:hover,
.flow-stage.active {
  border-color: var(--cs-accent);
  box-shadow: 0 0 0 1px var(--cs-accent-soft) inset;
}
.flow-stage.ok { border-top: 2px solid var(--cs-green); }
.flow-stage.running { border-top: 2px solid var(--cs-accent); background: var(--cs-accent-soft); }
.flow-stage.failed { border-top: 2px solid var(--cs-red); background: rgba(220, 38, 38, 0.05); }
.flow-stage.skipped { opacity: 0.6; }
.flow-stage.idle { border-top: 2px solid var(--cs-border-strong); }
.flow-kicker {
  font-family: var(--cs-mono);
  font-size: 8px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--cs-faint);
}
.flow-name {
  font-family: var(--cs-mono);
  font-size: 12px;
  font-weight: 700;
}
.flow-meta {
  font-family: var(--cs-mono);
  font-size: 9px;
  color: var(--cs-muted);
  white-space: nowrap;
}
.status-dot {
  display: inline-block;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--cs-faint);
  margin-right: 3px;
}
.ok .status-dot { background: var(--cs-green); }
.running .status-dot { background: var(--cs-accent); box-shadow: 0 0 6px var(--cs-accent); }
.failed .status-dot { background: var(--cs-red); }
.flow-arrow {
  align-self: center;
  color: var(--cs-faint);
  font-family: var(--cs-mono);
}
@media (max-width: 900px) {
  .flow-arrow { display: none; }
  .flow-stage { min-width: 110px; }
}
</style>
