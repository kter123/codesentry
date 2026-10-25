<template>
  <div>
    <page-header title="项目管理" subtitle="项目源码/仓库与 cron 定时扫描">
      <template #actions>
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
        <el-button @click="projectDialog = true">新建项目</el-button>
        <el-button type="primary" @click="openScheduleDialog()">新建定时</el-button>
      </template>
    </page-header>

    <error-alert :message="error" @retry="load" />

    <div class="panel">
      <h2 class="panel-title">项目</h2>
      <el-table v-loading="loading" :data="projects" size="small" row-key="id">
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="repo_path" label="本地路径" min-width="260" show-overflow-tooltip />
        <el-table-column prop="git_url" label="Git URL" min-width="220" show-overflow-tooltip />
        <el-table-column label="OSS" width="70">
          <template #default="{ row }">{{ row.oss ? '是' : '否' }}</template>
        </el-table-column>
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" @change="toggleProject(row)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openScheduleDialog(row.id)">加定时</el-button>
            <el-button link type="danger" @click="removeProject(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty :image-size="60" description="还没有项目" /></template>
      </el-table>
    </div>

    <div class="panel">
      <h2 class="panel-title">定时扫描</h2>
      <el-table v-loading="loading" :data="schedules" size="small" row-key="id">
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="project_name" label="项目" min-width="140" />
        <el-table-column prop="cron" label="Cron" width="150" />
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" @change="toggleSchedule(row)" />
          </template>
        </el-table-column>
        <el-table-column prop="next_run_at" label="下次运行" min-width="180" />
        <el-table-column prop="last_run_at" label="上次运行" min-width="180" />
        <el-table-column prop="last_scan_id" label="扫描" width="80" />
        <el-table-column prop="last_error" label="错误" min-width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button link type="success" :loading="runningId === row.id" @click="runNow(row)">
              立即运行
            </el-button>
            <el-button link type="danger" @click="removeSchedule(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty :image-size="60" description="还没有定时计划" /></template>
      </el-table>
      <div class="muted" style="margin-top: 8px; font-size: 12px">
        Cron 为 5 段（分 时 日 月 周，UTC）；后台每 30 秒检查一次。
      </div>
    </div>

    <el-dialog v-model="projectDialog" title="新建项目" width="560px">
      <el-form label-position="top">
        <el-form-item label="名称"><el-input v-model="projectForm.name" /></el-form-item>
        <el-form-item label="本地路径（work 根内，可留空）">
          <el-input v-model="projectForm.repo_path" placeholder="work/xxxx/src" />
        </el-form-item>
        <el-form-item label="Git URL（HTTPS，可留空）">
          <el-input v-model="projectForm.git_url" placeholder="https://github.com/org/repo.git" />
        </el-form-item>
        <el-form-item label="OSS"><el-switch v-model="projectForm.oss" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="projectDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createProject">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="scheduleDialog" title="新建定时扫描" width="520px">
      <el-form label-position="top">
        <el-form-item label="项目">
          <el-select v-model="scheduleForm.project_id" style="width: 100%">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称"><el-input v-model="scheduleForm.name" /></el-form-item>
        <el-form-item label="Cron（分 时 日 月 周）">
          <el-input v-model="scheduleForm.cron" placeholder="0 3 * * *" />
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="scheduleForm.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="scheduleDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createSchedule">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { api, errorMessage } from '@/api/client'
import ErrorAlert from '@/components/ErrorAlert.vue'
import PageHeader from '@/components/PageHeader.vue'

interface Project {
  id: number
  name: string
  repo_path: string
  git_url: string
  oss: boolean
  enabled: boolean
}

interface Schedule {
  id: number
  project_id: number
  project_name?: string
  name: string
  cron: string
  enabled: boolean
  next_run_at?: string | null
  last_run_at?: string | null
  last_scan_id?: number | null
  last_error?: string
}

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const projects = ref<Project[]>([])
const schedules = ref<Schedule[]>([])
const projectDialog = ref(false)
const scheduleDialog = ref(false)
const runningId = ref(0)
const projectForm = reactive({ name: '', repo_path: '', git_url: '', oss: false })
const scheduleForm = reactive({ project_id: 0, name: '', cron: '0 3 * * *', enabled: true })

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [p, s] = await Promise.all([
      api.get<{ projects?: Project[] }>('/api/projects'),
      api.get<{ schedules?: Schedule[] }>('/api/schedules'),
    ])
    projects.value = p.projects || []
    schedules.value = s.schedules || []
  } catch (e) {
    error.value = `加载失败：${errorMessage(e)}`
  } finally {
    loading.value = false
  }
}

async function createProject(): Promise<void> {
  saving.value = true
  try {
    await api.post('/api/projects', projectForm)
    ElMessage.success('项目已创建')
    projectDialog.value = false
    Object.assign(projectForm, { name: '', repo_path: '', git_url: '', oss: false })
    await load()
  } catch (e) {
    ElMessage.error(`创建失败：${errorMessage(e)}`)
  } finally {
    saving.value = false
  }
}

function openScheduleDialog(projectId = 0): void {
  scheduleForm.project_id = projectId || projects.value[0]?.id || 0
  scheduleForm.name = ''
  scheduleForm.cron = '0 3 * * *'
  scheduleForm.enabled = true
  scheduleDialog.value = true
}

async function createSchedule(): Promise<void> {
  saving.value = true
  try {
    await api.post('/api/schedules', scheduleForm)
    ElMessage.success('定时计划已创建')
    scheduleDialog.value = false
    await load()
  } catch (e) {
    ElMessage.error(`创建失败：${errorMessage(e)}`)
  } finally {
    saving.value = false
  }
}

async function toggleProject(row: Project): Promise<void> {
  try {
    await api.put(`/api/projects/${row.id}`, { enabled: !row.enabled })
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function toggleSchedule(row: Schedule): Promise<void> {
  try {
    await api.put(`/api/schedules/${row.id}`, { enabled: !row.enabled })
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function runNow(row: Schedule): Promise<void> {
  runningId.value = row.id
  try {
    const res = await api.post<{ scan_id: number }>(`/api/schedules/${row.id}/run`)
    ElMessage.success(`扫描已启动：#${res.scan_id}`)
    await load()
  } catch (e) {
    ElMessage.error(`启动失败：${errorMessage(e)}`)
  } finally {
    runningId.value = 0
  }
}

async function removeProject(row: Project): Promise<void> {
  if (!(await ElMessageBox.confirm(`删除项目 ${row.name}？`, '确认').catch(() => false))) return
  try {
    await api.del(`/api/projects/${row.id}`)
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function removeSchedule(row: Schedule): Promise<void> {
  if (!(await ElMessageBox.confirm(`删除定时 #${row.id}？`, '确认').catch(() => false))) return
  try {
    await api.del(`/api/schedules/${row.id}`)
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

onMounted(load)
</script>
