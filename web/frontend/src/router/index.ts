import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import AppLayout from '@/components/AppLayout.vue'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    public?: boolean
    activeMenu?: string
  }
}

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { title: '登录', public: true },
    },
    {
      // The app is served under /ui/; /ui (no trailing slash) is also served by the
      // backend catch-all, so normalize it to the router base root.
      path: '/ui',
      redirect: '/',
    },
    {
      path: '/',
      component: AppLayout,
      children: [
        {
          path: '',
          name: 'audit-home',
          component: () => import('@/views/AuditHomeView.vue'),
          meta: { title: 'Agent 审计' },
        },
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('@/views/OverviewView.vue'),
          meta: { title: '仪表盘' },
        },
        {
          path: 'instant',
          name: 'instant',
          component: () => import('@/views/InstantAnalysisView.vue'),
          meta: { title: '即时分析' },
        },
        {
          path: 'scans',
          name: 'scans',
          component: () => import('@/views/ScansView.vue'),
          meta: { title: '扫描管理' },
        },
        {
          path: 'projects',
          name: 'projects',
          component: () => import('@/views/ProjectsView.vue'),
          meta: { title: '项目与定时' },
        },
        {
          path: 'scans/:id',
          name: 'scan-detail',
          component: () => import('@/views/ScanDetailView.vue'),
          meta: { title: '扫描详情', activeMenu: '/scans' },
        },
        {
          path: 'scans/:id/workbench',
          name: 'scan-workbench',
          component: () => import('@/views/WorkbenchView.vue'),
          meta: { title: '审计工作台', activeMenu: '/scans' },
        },
        {
          path: 'scans/:id/graph',
          name: 'scan-graph',
          component: () => import('@/views/GraphView.vue'),
          meta: { title: '代码图', activeMenu: '/scans' },
        },
        {
          path: 'reviews',
          name: 'reviews',
          component: () => import('@/views/ReviewsView.vue'),
          meta: { title: '复核队列' },
        },
        {
          path: 'agents',
          name: 'agents',
          component: () => import('@/views/AgentsView.vue'),
          meta: { title: 'Agent 管理' },
        },
        {
          path: 'agents/:name',
          name: 'agent-detail',
          component: () => import('@/views/AgentDetailView.vue'),
          meta: { title: 'Agent 详情', activeMenu: '/agents' },
        },
        {
          path: 'llm',
          name: 'llm',
          component: () => import('@/views/LlmProfilesView.vue'),
          meta: { title: 'LLM 配置' },
        },
        {
          path: 'usage',
          name: 'usage',
          component: () => import('@/views/UsageView.vue'),
          meta: { title: '用量与配额' },
        },
        {
          path: 'prompts',
          name: 'prompts',
          component: () => import('@/views/PromptsView.vue'),
          meta: { title: 'Prompt 管理' },
        },
        {
          path: 'skills',
          name: 'skills',
          component: () => import('@/views/SkillsView.vue'),
          meta: { title: 'Skills 管理' },
        },
        {
          path: 'kb',
          name: 'knowledge',
          component: () => import('@/views/KnowledgeView.vue'),
          meta: { title: '知识库' },
        },
        {
          path: 'rules',
          name: 'rules',
          component: () => import('@/views/RulesView.vue'),
          meta: { title: '规则管理' },
        },
        {
          path: 'orchestration',
          name: 'orchestration',
          component: () => import('@/views/OrchestrationView.vue'),
          meta: { title: '编排模板' },
        },
        {
          path: 'audit',
          name: 'audit',
          component: () => import('@/views/AuditView.vue'),
          meta: { title: '配置审计' },
        },
        {
          path: 'settings',
          name: 'settings',
          component: () => import('@/views/SettingsView.vue'),
          meta: { title: '全局设置' },
        },
        {
          path: 'users',
          name: 'users',
          component: () => import('@/views/UsersView.vue'),
          meta: { title: '用户与 Token' },
        },
        {
          path: 'review/:scanId',
          redirect: (to) => ({ path: `/scans/${String(to.params.scanId)}` }),
        },
        {
          path: ':pathMatch(.*)*',
          name: 'not-found',
          component: () => import('@/views/NotFoundView.vue'),
          meta: { title: '页面不存在' },
        },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.loaded) {
    await auth.fetchMe()
  }
  if (to.meta.public) {
    if (to.name === 'login' && auth.authEnabled && auth.user) {
      return { path: '/' }
    }
    return true
  }
  if (auth.authEnabled && !auth.user) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  return true
})

export default router
