<template>
  <div ref="chartEl" class="eval-chart" />
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'

type EvalRow = Record<string, number | string | undefined>

const props = defineProps<{ rows: EvalRow[] }>()

const chartEl = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let observer: ResizeObserver | null = null

function pct(value: unknown): number {
  return Number(((Number(value) || 0) * 100).toFixed(1))
}

function render(): void {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)
  const rows = [...props.rows].reverse()
  const labels = rows.map((row) => `v${row.version ?? 'active'} · ${row.dataset ?? ''}`)
  const option: EChartsOption = {
    tooltip: { trigger: 'axis', valueFormatter: (value) => `${Number(value).toFixed(1)}%` },
    legend: { top: 0, textStyle: { color: '#64748b' } },
    grid: { left: 44, right: 42, top: 34, bottom: 52 },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#64748b', rotate: labels.length > 6 ? 28 : 0 },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
    },
    yAxis: [
      {
        type: 'value', name: '比例', max: 100,
        axisLabel: { color: '#64748b', formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#eef2f7' } },
      },
      {
        type: 'value', name: 'ECE', max: 100,
        axisLabel: { color: '#94a3b8', formatter: '{value}%' },
        splitLine: { show: false },
      },
    ],
    series: [
      { name: 'Recall', type: 'bar', data: rows.map((r) => pct(r.recall)), itemStyle: { color: '#2563eb', borderRadius: [4, 4, 0, 0] } },
      { name: 'Precision', type: 'bar', data: rows.map((r) => pct(r.precision)), itemStyle: { color: '#10b981', borderRadius: [4, 4, 0, 0] } },
      { name: 'FP Rate', type: 'bar', data: rows.map((r) => pct(r.fp_rate)), itemStyle: { color: '#ef4444', borderRadius: [4, 4, 0, 0] } },
      { name: 'ECE', type: 'line', yAxisIndex: 1, data: rows.map((r) => pct(r.ece)), symbolSize: 6, lineStyle: { color: '#f59e0b', width: 2 }, itemStyle: { color: '#f59e0b' } },
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
watch(() => props.rows, () => render(), { deep: true })
onUnmounted(() => {
  observer?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.eval-chart {
  width: 100%;
  height: 280px;
  margin-top: 12px;
}
</style>
