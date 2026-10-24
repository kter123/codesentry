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
        <el-menu-item v-for="item in menuItems" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>{{ item.label }}</template>
        </el-menu-item>
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
  Collection,
  Connection,
  Cpu,
  DataLine,
  DocumentChecked,
  EditPen,
  Expand,
  Fold,
  MagicStick,
  Odometer,
  Search,
  SetUp,
  Setting,
  Share,
  Tickets,
  User,
} from '@element-plus/icons-vue'

import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const isCollapse = ref(false)

const menuItems = [
  { path: '/', label: '概览', icon: Odometer },
  { path: '/scans', label: '扫描管理', icon: Search },
  { path: '/reviews', label: '复核队列', icon: DocumentChecked },
  { path: '/agents', label: 'Agent 管理', icon: Cpu },
  { path: '/llm', label: 'LLM 配置', icon: Connection },
  { path: '/usage', label: '用量与配额', icon: DataLine },
  { path: '/prompts', label: 'Prompt 管理', icon: EditPen },
  { path: '/skills', label: 'Skills 管理', icon: MagicStick },
  { path: '/kb', label: '知识库', icon: Collection },
  { path: '/rules', label: '规则管理', icon: SetUp },
  { path: '/orchestration', label: '编排模板', icon: Share },
  { path: '/audit', label: '配置审计', icon: Tickets },
  { path: '/settings', label: '全局设置', icon: Setting },
  { path: '/users', label: '用户与 Token', icon: User },
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
  if (window.innerWidth < 900) isCollapse.value = true
})
</script>
