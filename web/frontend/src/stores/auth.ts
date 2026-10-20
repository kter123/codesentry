import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { api } from '@/api/client'
import type { AuthUser, MeResponse } from '@/api/types'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  const authEnabled = ref(false)
  const loaded = ref(false)
  const loading = ref(false)
  const error = ref('')

  const isAuthenticated = computed(() => !authEnabled.value || !!user.value)
  const isAdmin = computed(() => !authEnabled.value || user.value?.role === 'admin')
  const displayName = computed(() => user.value?.display_name || user.value?.username || '未登录')
  const roleLabel = computed(() => {
    if (!authEnabled.value) return '本地模式'
    const role = user.value?.role
    return role ? role : '未知角色'
  })

  function applyMe(res: MeResponse): void {
    authEnabled.value = res.auth_enabled !== false
    if (res.user) {
      user.value = res.user
    } else if (res.username) {
      user.value = { username: res.username, role: res.role }
    } else {
      user.value = null
    }
  }

  async function fetchMe(force = false): Promise<void> {
    if (loaded.value && !force) return
    loading.value = true
    error.value = ''
    try {
      const res = await api.get<MeResponse>('/api/auth/me', undefined, {
        skipAuthRedirect: true,
      })
      applyMe(res)
    } catch (e) {
      const status = (e as { status?: number }).status
      if (status === 401) {
        authEnabled.value = true
        user.value = null
      } else {
        authEnabled.value = false
        user.value = null
        error.value = e instanceof Error ? e.message : String(e)
      }
    } finally {
      loading.value = false
      loaded.value = true
    }
  }

  async function login(username: string, password: string): Promise<void> {
    const res = await api.post<{ ok: boolean; user: AuthUser }>(
      '/api/auth/login',
      { username, password },
      { skipAuthRedirect: true },
    )
    user.value = res.user
    authEnabled.value = true
    loaded.value = true
    error.value = ''
  }

  async function logout(): Promise<void> {
    try {
      await api.post('/api/auth/logout', undefined, { skipAuthRedirect: true })
    } catch {
      // 即使后端不可用也清理本地会话
    }
    user.value = null
    loaded.value = true
  }

  return {
    user,
    authEnabled,
    loaded,
    loading,
    error,
    isAuthenticated,
    isAdmin,
    displayName,
    roleLabel,
    fetchMe,
    login,
    logout,
  }
})
