<template>
  <div>
    <page-header title="审计任务" subtitle="上传压缩包 / Git 仓库 / Diff，或查看历史审计任务">
      <template #actions>
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
      </template>
    </page-header>

    <div class="panel">
      <h2 class="panel-title">发起新扫描</h2>
      <el-tabs v-model="mode">
        <el-tab-pane label="上传压缩包" name="file">
          <el-upload
            v-model:file-list="fileList"
            drag
            :auto-upload="false"
            :limit="1"
            accept=".zip,.tar,.tar.gz,.tgz"
            :on-exceed="onExceed"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖拽 zip / tar.gz 到此处，或<em>点击选择</em></div>
            <template #tip>
              <div class="el-upload__tip">支持 .zip / .tar / .tar.gz / .tgz，最大 500 MB</div>
            </template>
          </el-upload>
        </el-tab-pane>
        <el-tab-pane label="Git 仓库" name="git">
          <el-input
            v-model="gitUrl"
            placeholder="https://github.com/org/repo.git"
            clearable
          />
          <div class="el-upload__tip">仅允许 https 公网地址；服务端会执行浅克隆。</div>
        </el-tab-pane>
        <el-tab-pane label="Diff 文本" name="diff">
          <el-input
            v-model="diffText"
            class="code-input"
            type="textarea"
            :rows="10"
            placeholder="粘贴 unified diff（<= 5 MB）"
          />
        </el-tab-pane>
      </el-tabs>

      <div class="toolbar" style="margin-top: 12px">
        <el-checkbox v-model="oss">标记为 OSS 许可仓库</el-checkbox>
        <div class="grow" />
        <el-button type="primary" :loading="submitting" @click="submit">开始扫描</el-button>
      </div>
      <el-alert
        v-if="uploadError"
        type="error"
        :title="uploadError"
        show-icon
        :closable="false"
      />
    </div>

    <div class="panel">
      <div class="toolbar">
        <h2 class="panel-title" style="margin: 0">扫描历史</h2>
        <div class="grow" />
        <el-input
          v-model="filter"
          placeholder="按仓库路径过滤"
          clearable
          style="width: 240px"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </div>
      <error-alert :message="error" @retry="load" />
      <el-table
        v-loading="loading"
        :data="filteredScans"
        row-key="id"
        @row-click="openScan"
      >
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="repo_path" label="仓库路径" min-width="280" show-overflow-tooltip />
        <el-table-column label="状态" width="120">
          <template #default="{ row }"><status-tag :status="row.status" /></template>
        </el-table-column>
        <el-table-column prop="mode" label="模式" width="100" />
        <el-table-column label="OSS" width="80">
          <template #default="{ row }">{{ row.OSS ? '是' : '否' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openScan(row)">详情</el-button>
            <el-button link type="danger" @click.stop="removeScan(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty
            :image-size="80"
            :description="filter ? '没有匹配的扫描' : '还没有扫描记录'"
          />
        </template>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadUserFile } from 'element-plus'
import { Refresh, Search, UploadFilled } from '@element-plus/icons-vue'

import { api, errorMessage } from '@/api/client'
import type { ScanRow } from '@/api/types'
import { useScansStore } from '@/stores/scans'
import ErrorAlert from '@/components/ErrorAlert.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'

const router = useRouter()
const mode = ref<'file' | 'git' | 'diff'>('file')
const fileList = ref<UploadUserFile[]>([])
const gitUrl = ref('')
const diffText = ref('')
const oss = ref(false)
const submitting = ref(false)
const uploadError = ref('')

const scanStore = useScansStore()
const { scans, loading, error } = storeToRefs(scanStore)
const filter = ref('')

const filteredScans = computed(() => {
  const needle = filter.value.trim().toLowerCase()
  if (!needle) return scans.value
  return scans.value.filter((scan) => (scan.repo_path || '').toLowerCase().includes(needle))
})

function onExceed(files: File[]): void {
  fileList.value = [{ name: files[0]?.name ?? 'upload', raw: files[0] } as UploadUserFile]
}

function load(): Promise<void> {
  return scanStore.fetchScans(true)
}

async function submit(): Promise<void> {
  uploadError.value = ''
  const form = new FormData()
  const query: Record<string, string> = { oss: oss.value ? 'true' : 'false' }

  if (mode.value === 'file') {
    const file = fileList.value[0]?.raw
    if (!file) {
      uploadError.value = '请先选择一个压缩包'
      return
    }
    form.append('file', file)
  } else if (mode.value === 'git') {
    if (!gitUrl.value.trim()) {
      uploadError.value = '请输入 Git 仓库地址'
      return
    }
    query.git_url = gitUrl.value.trim()
  } else {
    if (!diffText.value.trim()) {
      uploadError.value = '请粘贴 diff 文本'
      return
    }
    form.append('diff_text', diffText.value)
  }

  submitting.value = true
  try {
    const res = await api.postForm<{ scan_id: number }>('/api/scans', form, { query })
    ElMessage.success(`扫描 #${res.scan_id} 已创建`)
    fileList.value = []
    gitUrl.value = ''
    diffText.value = ''
    await load()
    await router.push(`/scans/${res.scan_id}`)
  } catch (e) {
    uploadError.value = errorMessage(e)
  } finally {
    submitting.value = false
  }
}

function openScan(row: ScanRow): void {
  void router.push(`/scans/${row.id}`)
}

async function removeScan(row: ScanRow): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认删除扫描 #${row.id}？将同时删除 findings、时间线与工作目录。`,
      '删除扫描',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await scanStore.removeScan(row.id)
    ElMessage.success(`扫描 #${row.id} 已删除`)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

onMounted(load)
</script>
