<template>
  <div>
    <page-header title="即时分析" subtitle="粘贴代码/单文件，直接进入图审计工作台">
      <template #actions>
        <el-button @click="router.push('/scans')">扫描管理</el-button>
      </template>
    </page-header>
    <error-alert :message="error" :retryable="false" />
    <div class="panel">
      <el-form label-position="top">
        <el-row :gutter="12">
          <el-col :xs="24" :sm="12">
            <el-form-item label="文件名">
              <el-input v-model="form.filename" placeholder="snippet.py / app.js / Main.java" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="OSS">
              <el-switch v-model="form.oss" />
              <span class="muted" style="margin-left: 8px">开源代码才启用 CodeQL</span>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="代码">
          <el-input v-model="form.code" type="textarea" :rows="18" class="code-input"
                    placeholder="粘贴单个文件源码，平台会在临时仓库中执行正常扫描链路" />
        </el-form-item>
      </el-form>
      <div class="toolbar">
        <el-button type="primary" :loading="starting" @click="start">开始分析</el-button>
        <span class="muted">不会执行你粘贴的代码；只做静态分析/沙箱验证</span>
      </div>
      <el-alert v-if="scanId" type="success" :closable="false" show-icon
                :title="`扫描 #${scanId} 已启动`" style="margin-top: 10px" />
      <div v-if="scanId" class="toolbar" style="margin-top: 8px">
        <el-button type="primary" @click="router.push(`/scans/${scanId}/workbench`)">打开审计工作台</el-button>
        <el-button @click="router.push(`/scans/${scanId}`)">扫描详情</el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api, errorMessage } from '@/api/client'
import ErrorAlert from '@/components/ErrorAlert.vue'
import PageHeader from '@/components/PageHeader.vue'

const router = useRouter()
const form = reactive({ filename: 'snippet.py', code: '', oss: false })
const starting = ref(false)
const scanId = ref<number | null>(null)
const error = ref('')

async function start(): Promise<void> {
  if (!form.code.trim()) {
    error.value = '请先粘贴代码'
    return
  }
  starting.value = true
  error.value = ''
  try {
    const res = await api.post<{ scan_id: number }>('/api/instant-analysis', form)
    scanId.value = res.scan_id
  } catch (e) {
    error.value = `启动失败：${errorMessage(e)}`
  } finally {
    starting.value = false
  }
}
</script>
