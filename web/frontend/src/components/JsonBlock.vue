<template>
  <pre class="pre-block" :class="{ light }">{{ text }}</pre>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    value: unknown
    light?: boolean
  }>(),
  { light: false },
)

const text = computed(() => {
  if (props.value === undefined) return '—'
  if (typeof props.value === 'string') return props.value
  try {
    return JSON.stringify(props.value, null, 2)
  } catch {
    return String(props.value)
  }
})
</script>
