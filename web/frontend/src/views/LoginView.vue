<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand">
        <span class="app-brand-mark">CS</span>
        <span>CodeSentry</span>
      </div>
      <p class="login-sub">多智能体源码安全审计控制台</p>

      <template v-if="!auth.authEnabled && auth.loaded">
        <el-result icon="success" title="本地模式" sub-title="认证已在后端关闭，当前以本地管理员身份访问。">
          <template #extra>
            <el-button type="primary" @click="enter">进入控制台</el-button>
          </template>
        </el-result>
        <div class="login-hint">
          如需启用登录与 RBAC，请设置 <span class="mono">CODESENTRY_AUTH_ENABLED=true</span>，
          并通过 <span class="mono">CODESENTRY_ADMIN_USER</span> /
          <span class="mono">CODESENTRY_ADMIN_PASSWORD</span> 引导管理员账号。
        </div>
      </template>

      <template v-else>
        <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" />
        <el-form
          v-if="auth.loaded"
          class="login-form"
          label-position="top"
          @submit.prevent="submit"
        >
          <el-form-item label="用户名">
            <el-input v-model="username" autocomplete="username" placeholder="admin" autofocus />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="password"
              type="password"
              show-password
              autocomplete="current-password"
              placeholder="请输入密码"
              @keyup.enter="submit"
            />
          </el-form-item>
          <el-button
            type="primary"
            native-type="submit"
            :loading="submitting"
            style="width: 100%"
          >
            登录
          </el-button>
        </el-form>
        <div v-else class="login-hint">正在检查会话状态…</div>
        <div class="login-hint">
          认证开启时，账号由管理员在「用户与 Token」页面创建；首次启动可用环境变量引导管理员。
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { errorMessage, stripAppBase } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const submitting = ref(false)
const error = ref('')

function targetPath(): string {
  const redirect = route.query.redirect
  if (typeof redirect === 'string' && redirect.startsWith('/') && !redirect.startsWith('//')) {
    return stripAppBase(redirect)
  }
  return '/'
}

async function enter(): Promise<void> {
  await router.replace(targetPath())
}

async function submit(): Promise<void> {
  if (!username.value.trim() || !password.value) {
    error.value = '请输入用户名和密码'
    return
  }
  submitting.value = true
  error.value = ''
  try {
    await auth.login(username.value.trim(), password.value)
    ElMessage.success('登录成功')
    await router.replace(targetPath())
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  if (!auth.loaded) await auth.fetchMe()
  if (auth.authEnabled && auth.user) await router.replace(targetPath())
})
</script>
