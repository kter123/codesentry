<template>
  <el-tag :type="tagType" :effect="effect" size="small">{{ status || '—' }}</el-tag>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    status?: string
    effect?: 'dark' | 'light' | 'plain'
  }>(),
  { status: '', effect: 'light' },
)

const tagType = computed<'success' | 'warning' | 'danger' | 'info' | 'primary'>(() => {
  const value = (props.status || '').toLowerCase()
  if (['ok', 'success', 'done', 'ready', 'completed', 'confirmed', 'active', 'built'].includes(value)) {
    return 'success'
  }
  if (['running', 'pending', 'queued', 'interrupted', 'degraded', 'plausible', 'warn'].includes(value)) {
    return 'warning'
  }
  if (['failed', 'error', 'rejected', 'critical', 'high', 'disabled'].includes(value)) {
    return 'danger'
  }
  if (['medium', 'adjust'].includes(value)) return 'primary'
  if (['low', 'info', 'skipped'].includes(value)) return 'info'
  return 'info'
})
</script>
