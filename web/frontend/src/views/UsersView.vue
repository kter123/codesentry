<template>
  <div>
    <page-header title="用户与 Token" subtitle="RBAC 用户管理与 CI/机器人 API Token">
      <template #actions>
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
      </template>
    </page-header>

    <el-alert
      v-if="!auth.isAdmin"
      type="warning"
      show-icon
      :closable="false"
      title="用户与 Token 管理需要 admin 角色；当前账号可能只能查看或会被后端拒绝。"
      style="margin-bottom: 14px"
    />
    <error-alert :message="error" @retry="load" />

    <div class="panel">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="用户" name="users">
          <div class="toolbar">
            <span class="muted">共 {{ users.length }} 个用户</span>
            <div class="grow" />
            <el-button type="primary" size="small" @click="openCreateUser">新建用户</el-button>
          </div>
          <el-table v-loading="loading" :data="users" row-key="id" size="small">
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="username" label="用户名" min-width="140" />
            <el-table-column prop="display_name" label="显示名" min-width="140" />
            <el-table-column label="角色" width="110">
              <template #default="{ row }">
                <el-tag size="small" :type="roleType(row.role)">{{ row.role }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="100">
              <template #default="{ row }">
                <el-switch
                  :model-value="row.enabled !== false"
                  :loading="userSaving[row.id] === true"
                  @change="(value: boolean) => toggleUser(row, value)"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="110" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openEditUser(row)">编辑</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty :image-size="70" description="没有用户（认证关闭时可能为空）" />
            </template>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="API Tokens" name="tokens">
          <div class="toolbar">
            <span class="muted">共 {{ tokens.length }} 个 Token</span>
            <div class="grow" />
            <el-button type="primary" size="small" @click="openCreateToken">新建 Token</el-button>
          </div>
          <el-table v-loading="loading" :data="tokens" row-key="id" size="small">
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="name" label="名称" min-width="150" />
            <el-table-column label="前缀" width="130">
              <template #default="{ row }"><span class="mono">{{ row.prefix || '—' }}</span></template>
            </el-table-column>
            <el-table-column label="用户" width="90">
              <template #default="{ row }">{{ row.user_id ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="Scopes" min-width="190">
              <template #default="{ row }">
                <div class="inline-tags">
                  <el-tag v-for="scope in scopeList(row.scopes)" :key="scope" size="small" effect="plain">
                    {{ scope }}
                  </el-tag>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="过期" min-width="150">
              <template #default="{ row }">{{ row.expires_at || '永不过期' }}</template>
            </el-table-column>
            <el-table-column label="最近使用" min-width="150">
              <template #default="{ row }">{{ row.last_used_at || '—' }}</template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" min-width="150" show-overflow-tooltip />
            <el-table-column label="操作" width="100" fixed="right">
              <template #default="{ row }">
                <el-button link type="danger" @click="revokeToken(row)">吊销</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty :image-size="70" description="还没有 API Token" />
            </template>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>

    <el-dialog
      v-model="userDialog"
      :title="userMode === 'create' ? '新建用户' : `编辑用户 #${userForm.id ?? ''}`"
      width="500px"
      destroy-on-close
    >
      <el-alert v-if="userError" type="error" :title="userError" :closable="false" show-icon style="margin-bottom: 12px" />
      <el-form label-position="top">
        <el-form-item label="用户名">
          <el-input v-model="userForm.username" :disabled="userMode === 'edit'" />
        </el-form-item>
        <el-form-item v-if="userMode === 'create'" label="密码">
          <el-input v-model="userForm.password" type="password" show-password />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="userForm.display_name" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="userForm.role" style="width: 100%">
            <el-option label="admin" value="admin" />
            <el-option label="analyst" value="analyst" />
            <el-option label="viewer" value="viewer" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="userMode === 'edit'" label="启用">
          <el-switch v-model="userForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="userDialog = false">取消</el-button>
        <el-button type="primary" :loading="userSavingDialog" @click="saveUser">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="tokenDialog" title="新建 API Token" width="520px" destroy-on-close>
      <el-alert v-if="tokenError" type="error" :title="tokenError" :closable="false" show-icon style="margin-bottom: 12px" />
      <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model="tokenForm.name" placeholder="ci-runner" />
        </el-form-item>
        <el-form-item label="绑定用户（可选）">
          <el-select v-model="tokenForm.user_id" clearable placeholder="不绑定用户" style="width: 100%">
            <el-option v-for="user in users" :key="user.id" :label="user.username" :value="user.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="Scopes（逗号分隔）">
          <el-input v-model="tokenForm.scopes" placeholder="scan:read,scan:write" />
        </el-form-item>
        <el-form-item label="有效天数（0 表示永不过期）">
          <el-input-number v-model="tokenForm.expires_days" :min="0" :max="3650" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="tokenDialog = false">取消</el-button>
        <el-button type="primary" :loading="tokenSaving" @click="createToken">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="revealDialog" title="API Token 已创建" width="620px" :close-on-click-modal="false">
      <el-alert
        type="warning"
        show-icon
        :closable="false"
        title="Token 只显示一次，请立即复制并妥善保存。"
        style="margin-bottom: 12px"
      />
      <pre class="pre-block light token-value">{{ revealedToken }}</pre>
      <template #footer>
        <el-button @click="revealDialog = false">关闭</el-button>
        <el-button type="primary" @click="copyToken">复制 Token</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { api, errorMessage } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import ErrorAlert from '@/components/ErrorAlert.vue'
import PageHeader from '@/components/PageHeader.vue'

interface UserRow {
  id: number
  username: string
  display_name?: string
  role?: string
  enabled?: boolean
}

interface TokenRow {
  id: number
  user_id?: number | null
  name: string
  prefix?: string
  scopes?: unknown
  expires_at?: string | null
  last_used_at?: string | null
  created_at?: string
}

const auth = useAuthStore()

const loading = ref(false)
const error = ref('')
const activeTab = ref<'users' | 'tokens'>('users')
const users = ref<UserRow[]>([])
const tokens = ref<TokenRow[]>([])
const userSaving = reactive<Record<number, boolean>>({})

const userDialog = ref(false)
const userMode = ref<'create' | 'edit'>('create')
const userError = ref('')
const userSavingDialog = ref(false)
const userForm = reactive({
  id: null as number | null,
  username: '',
  password: '',
  display_name: '',
  role: 'viewer',
  enabled: true,
})

const tokenDialog = ref(false)
const tokenError = ref('')
const tokenSaving = ref(false)
const tokenForm = reactive({
  name: '',
  user_id: undefined as number | undefined,
  scopes: 'scan:read,scan:write',
  expires_days: 0,
})

const revealDialog = ref(false)
const revealedToken = ref('')

function roleType(role?: string): 'danger' | 'warning' | 'info' {
  if (role === 'admin') return 'danger'
  if (role === 'analyst') return 'warning'
  return 'info'
}

function scopeList(scopes: unknown): string[] {
  if (Array.isArray(scopes)) return scopes.map((item) => String(item))
  if (typeof scopes === 'string') {
    try {
      const parsed = JSON.parse(scopes)
      if (Array.isArray(parsed)) return parsed.map((item) => String(item))
    } catch {
      return scopes.split(',').map((item) => item.trim()).filter(Boolean)
    }
  }
  return []
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  const [usersRes, tokensRes] = await Promise.allSettled([
    api.get<{ users: UserRow[] }>('/api/users'),
    api.get<{ tokens: TokenRow[] }>('/api/api-tokens'),
  ])
  if (usersRes.status === 'fulfilled') {
    users.value = usersRes.value?.users ?? []
  } else {
    error.value = `加载用户失败：${errorMessage(usersRes.reason)}`
  }
  if (tokensRes.status === 'fulfilled') {
    tokens.value = tokensRes.value?.tokens ?? []
  } else if (!error.value) {
    error.value = `加载 API Token 失败：${errorMessage(tokensRes.reason)}`
  }
  loading.value = false
}

function openCreateUser(): void {
  userMode.value = 'create'
  userError.value = ''
  Object.assign(userForm, {
    id: null,
    username: '',
    password: '',
    display_name: '',
    role: 'viewer',
    enabled: true,
  })
  userDialog.value = true
}

function openEditUser(row: UserRow): void {
  userMode.value = 'edit'
  userError.value = ''
  Object.assign(userForm, {
    id: row.id,
    username: row.username,
    password: '',
    display_name: row.display_name ?? '',
    role: row.role ?? 'viewer',
    enabled: row.enabled !== false,
  })
  userDialog.value = true
}

async function saveUser(): Promise<void> {
  userError.value = ''
  if (userMode.value === 'create' && (!userForm.username.trim() || !userForm.password)) {
    userError.value = '用户名与密码不能为空'
    return
  }
  userSavingDialog.value = true
  try {
    if (userMode.value === 'create') {
      await api.post('/api/users', {
        username: userForm.username.trim(),
        password: userForm.password,
        role: userForm.role,
        display_name: userForm.display_name,
      })
      ElMessage.success('用户已创建')
    } else if (userForm.id !== null) {
      await api.put(`/api/users/${userForm.id}`, {
        role: userForm.role,
        enabled: userForm.enabled,
        display_name: userForm.display_name,
      })
      ElMessage.success('用户已更新')
    }
    userDialog.value = false
    await load()
  } catch (e) {
    userError.value = errorMessage(e)
  } finally {
    userSavingDialog.value = false
  }
}

async function toggleUser(row: UserRow, enabled: boolean): Promise<void> {
  userSaving[row.id] = true
  try {
    await api.put(`/api/users/${row.id}`, { enabled })
    row.enabled = enabled
    ElMessage.success(`用户 ${row.username} 已${enabled ? '启用' : '停用'}`)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    userSaving[row.id] = false
  }
}

function openCreateToken(): void {
  tokenError.value = ''
  Object.assign(tokenForm, {
    name: '',
    user_id: undefined,
    scopes: 'scan:read,scan:write',
    expires_days: 0,
  })
  tokenDialog.value = true
}

async function createToken(): Promise<void> {
  tokenError.value = ''
  if (!tokenForm.name.trim()) {
    tokenError.value = '请填写 Token 名称'
    return
  }
  tokenSaving.value = true
  try {
    const res = await api.post<{ token: TokenRow & { token?: string } }>('/api/api-tokens', {
      name: tokenForm.name.trim(),
      user_id: tokenForm.user_id ?? null,
      scopes: tokenForm.scopes
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
      expires_days: tokenForm.expires_days > 0 ? tokenForm.expires_days : null,
    })
    tokenDialog.value = false
    revealedToken.value = String(res?.token?.token || '')
    revealDialog.value = true
    await load()
  } catch (e) {
    tokenError.value = errorMessage(e)
  } finally {
    tokenSaving.value = false
  }
}

async function revokeToken(row: TokenRow): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认吊销 Token「${row.name}」？使用该 Token 的 CI 将立即失效。`,
      '吊销 API Token',
      { type: 'warning', confirmButtonText: '吊销', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await api.post(`/api/api-tokens/${row.id}/revoke`)
    ElMessage.success('Token 已吊销')
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function copyToken(): Promise<void> {
  try {
    await navigator.clipboard.writeText(revealedToken.value)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选择文本复制')
  }
}

onMounted(load)
</script>

<style scoped>
.token-value {
  user-select: all;
  word-break: break-all;
}
</style>
