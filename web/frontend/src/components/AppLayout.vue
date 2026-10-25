<template>
  <el-container class="app-shell">
    <el-aside class="app-aside" :width="isCollapse ? '64px' : '232px'">
      <div class="app-brand">
        <span class="app-brand-mark">CS</span>
        <span v-if="!isCollapse">CodeSentry</span>
      </div>
      <el-menu
        class="app-menu"
        :default-active="activeMenu"
        :collapse="isCollapse"
        :collapse-transition="false"
        router
      >
        <template v-for="group in menuGroups" :key="group.label">
          <div v-if="!isCollapse" class="menu-group-label">{{ group.label }}</div>
          <el-menu-item v-for="item in group.items" :key="item.path" :index="item.path">
            <el-icon><component :is="item.icon" /></el-icon>
            <template #title>{{ item.label }}</template>
          </el-menu-item>
        </template>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="app-header">
        <el-button text circle :aria-label="isCollapse ? '展开菜单' : '收起菜单'" @click="toggle">
          <el-icon :size="18">
            <Expand v-if="isCollapse" />
            <Fold v-else />
          </el-icon>
        </el-button>
        <el-breadcrumb separator="/">
          <el-breadcrumb-item :to="{ path: '/' }">CodeSentry</el-breadcrumb-item>
          <el-breadcrumb-item v-if="route.meta.title">{{ route.meta.title }}</el-breadcrumb-item>
        </el-breadcrumb>
        <div class="header-spacer" />
        <el-tag size="small" type="success" effect="dark" class="live-tag">
          <span class="live-dot" /> {{ healthLabel }}
        </el-tag>
        <el-button text circle :aria-label="theme === 'dark' ? '切换浅色' : '切换深色'" @click="toggleTheme">
          <el-icon :size="17"><Sunny v-if="theme === 'dark'" /><Moon v-else /></el-icon>
        </el-button>
        <el-tag v-if="!auth.authEnabled" size="small" type="info">本地模式</el-tag>
        <el-dropdown trigger="click" @command="onCommand">
          <span class="user-trigger">
            <el-avatar :size="28">{{ initials }}</el-avatar>
            <span>{{ auth.displayName }}</span>
            <el-tag size="small" effect="plain">{{ auth.roleLabel }}</el-tag>
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>{{ auth.user?.username || 'local' }}</el-dropdown-item>
              <el-dropdown-item command="settings">全局设置</el-dropdown-item>
              <el-dropdown-item v-if="auth.authEnabled" command="logout" divided>
                退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>

      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowDown,
  Calendar,
  Collection,
  Connection,
  Cpu,
  DataLine,
  Lightning,
  DocumentChecked,
  EditPen,
  Expand,
  Fold,
  MagicStick,
  Moon,
  Odometer,
  Search,
  SetUp,
  Setting,
  Share,
  Sunny,
  Tickets,
  User,
} from '@element-plus/icons-vue'

import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const isCollapse = ref(false)
const theme = ref<'dark' | 'light'>('light')
const healthLabel = ref('CONNECTED')

const menuGroups = [
  {
    label: 'Workspace',
    items: [
      { path: '/', label: 'Agent 审计', icon: Cpu },
      { path: '/dashboard', label: '仪表盘', icon: Odometer },
      { path: '/instant', label: '即时分析', icon: Lightning },
      { path: '/scans', label: '审计任务', icon: Search },
      { path: '/projects', label: '项目管理', icon: Calendar },
      { path: '/reviews', label: '复核队列', icon: DocumentChecked },
    ],
  },
  {
    label: 'Control Plane',
    items: [
      { path: '/agents', label: 'Agent 管理', icon: Cpu },
      { path: '/llm', label: 'LLM 配置', icon: Connection },
      { path: '/usage', label: '用量与配额', icon: DataLine },
      { path: '/prompts', label: 'Prompt 管理', icon: EditPen },
      { path: '/skills', label: 'Skills 管理', icon: MagicStick },
      { path: '/kb', label: '知识库', icon: Collection },
      { path: '/rules', label: '审计规则', icon: SetUp },
      { path: '/orchestration', label: '编排模板', icon: Share },
    ],
  },
  {
    label: 'System',
    items: [
      { path: '/audit', label: '配置审计', icon: Tickets },
      { path: '/settings', label: '全局设置', icon: Setting },
      { path: '/users', label: '用户与 Token', icon: User },
    ],
  },
]

const activeMenu = computed(() => {
  const configured = route.meta.activeMenu
  if (typeof configured === 'string' && configured) return configured
  if (route.path.startsWith('/scans/')) return '/scans'
  if (route.path.startsWith('/agents/')) return '/agents'
  return route.path
})

const initials = computed(() => {
  const name = auth.user?.display_name || auth.user?.username || 'local'
  return name.slice(0, 2).toUpperCase()
})

function toggle(): void {
  isCollapse.value = !isCollapse.value
}

function applyTheme(value: 'dark' | 'light'): void {
  theme.value = value
  document.documentElement.dataset.theme = value
  localStorage.setItem('codesentry.theme', value)
}

function toggleTheme(): void {
  applyTheme(theme.value === 'dark' ? 'light' : 'dark')
}

async function onCommand(command: string): Promise<void> {
  if (command === 'settings') {
    await router.push('/settings')
    return
  }
  if (command === 'logout') {
    await auth.logout()
    await router.replace('/login')
  }
}

onMounted(() => {
  const stored = localStorage.getItem('codesentry.theme')
  applyTheme(stored === 'dark' ? 'dark' : 'light')
  if (window.innerWidth < 900) isCollapse.value = true
  void fetch('/api/health')
    .then((r) => (r.ok ? 'CONNECTED' : 'DEGRADED'))
    .catch(() => 'OFFLINE')
    .then((label) => { healthLabel.value = label })
})
</script>
