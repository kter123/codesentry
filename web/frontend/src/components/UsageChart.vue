<template>
  <div ref="chartEl" class="usage-chart" />
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'

import type { UsageRow } from '@/api/types'

const props = withDefaults(
  defineProps<{
    rows: UsageRow[]
    metric?: 'tokens' | 'cost_usd' | 'calls'
  }>(),
  { metric: 'tokens' },
)

const chartEl = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let observer: ResizeObserver | null = null

function render(): void {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)
  const labels = props.rows.map((row) => row.key || '(empty)')
  const values = props.rows.map((row) => Number(row[props.metric] ?? 0))
  const option: EChartsOption = {
    grid: { left: 48, right: 20, top: 24, bottom: 64 },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value) =>
        props.metric === 'cost_usd'
          ? `$${Number(value).toFixed(4)}`
          : Number(value).toLocaleString(),
    },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { interval: 0, rotate: labels.length > 8 ? 35 : 0, color: '#64748b' },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: '#eef2f7' } },
      axisLabel: { color: '#64748b' },
    },
    series: [
      {
        type: 'bar',
        data: values,
        barMaxWidth: 38,
        itemStyle: { color: '#2563eb', borderRadius: [6, 6, 0, 0] },
        emphasis: { itemStyle: { color: '#1d4ed8' } },
      },
    ],
  }
  chart.setOption(option, true)
  chart.resize()
}

onMounted(() => {
  render()
  if (chartEl.value) {
    observer = new ResizeObserver(() => chart?.resize())
    observer.observe(chartEl.value)
  }
})

watch(
  () => [props.rows, props.metric],
  () => render(),
  { deep: true },
)

onUnmounted(() => {
  observer?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.usage-chart {
  width: 100%;
  height: 300px;
}
</style>
