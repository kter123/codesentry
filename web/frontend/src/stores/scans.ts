import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { api, errorMessage } from '@/api/client'
import type { ScanRow } from '@/api/types'

/** Shared scan list state: uploads, deletes and detail views stay in sync. */
export const useScansStore = defineStore('scans', () => {
  const scans = ref<ScanRow[]>([])
  const loading = ref(false)
  const error = ref('')
  const loaded = ref(false)
  const lastLoadedAt = ref<number | null>(null)

  const running = computed(() => scans.value.filter((scan) => scan.status === 'running'))
  const recent = computed(() =>
    [...scans.value].sort((a, b) => String(b.created ?? '').localeCompare(String(a.created ?? ''))),
  )

  async function fetchScans(force = false): Promise<void> {
    if (loading.value) return
    if (loaded.value && !force) return
    loading.value = true
    error.value = ''
    try {
      const res = await api.get<ScanRow[]>('/api/scans')
      scans.value = Array.isArray(res) ? res : []
      loaded.value = true
      lastLoadedAt.value = Date.now()
    } catch (e) {
      error.value = `加载扫描列表失败：${errorMessage(e)}`
    } finally {
      loading.value = false
    }
  }

  async function removeScan(scanId: number): Promise<void> {
    await api.del(`/api/scans/${scanId}`)
    scans.value = scans.value.filter((scan) => scan.id !== scanId)
  }

  function upsertScan(row: ScanRow): void {
    const index = scans.value.findIndex((scan) => scan.id === row.id)
    if (index >= 0) scans.value.splice(index, 1, { ...scans.value[index], ...row })
    else scans.value.unshift(row)
  }

  function reset(): void {
    scans.value = []
    loaded.value = false
    lastLoadedAt.value = null
    error.value = ''
  }

  return {
    scans,
    loading,
    error,
    loaded,
    lastLoadedAt,
    running,
    recent,
    fetchScans,
    removeScan,
    upsertScan,
    reset,
  }
})
