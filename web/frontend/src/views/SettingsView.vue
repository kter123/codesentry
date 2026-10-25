<template>
  <div>
    <page-header title="全局设置" subtitle="全局兜底 LLM 与 Embedding 配置（密钥仅掩码回显）">
      <template #actions>
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
      </template>
    </page-header>

    <el-row :gutter="18">
      <el-col :xs="24" :lg="12">
        <div class="panel">
          <h2 class="panel-title">LLM 兜底配置</h2>
          <el-alert
            v-if="errors.llm"
            type="error"
            :title="errors.llm"
            :closable="false"
            show-icon
            style="margin-bottom: 10px"
          />
          <el-form label-position="top" :disabled="loading">
            <el-form-item label="Base URL">
              <el-input v-model="llm.model_base_url" placeholder="https://api.openai.com/v1" />
            </el-form-item>
            <el-form-item label="API Key">
              <el-input v-model="llm.model_api_key" type="password" show-password />
              <el-checkbox v-model="clearKeys.llm" style="margin-top: 6px">
                清空已保存的 API Key
              </el-checkbox>
            </el-form-item>
            <el-form-item label="Fast Model">
              <el-input v-model="llm.fast_model" placeholder="gpt-4o-mini" />
            </el-form-item>
            <el-form-item label="Deep Model">
              <el-input v-model="llm.deep_model" placeholder="gpt-4o" />
            </el-form-item>
          </el-form>
          <div class="toolbar" style="margin-bottom: 0">
            <el-button type="primary" :loading="saving.llm" @click="save('llm')">保存</el-button>
            <el-button :loading="testing.llm" @click="test('llm')">测试连接</el-button>
          </div>
          <el-alert
            v-if="testResults.llm"
            :type="testResults.llm.ok ? 'success' : 'error'"
            :title="testResults.llm.text"
            :closable="false"
            show-icon
            style="margin-top: 12px"
          />
        </div>
      </el-col>

      <el-col :xs="24" :lg="12">
        <div class="panel">
          <h2 class="panel-title">Embedding 配置</h2>
          <el-alert
            v-if="errors.embedding"
            type="error"
            :title="errors.embedding"
            :closable="false"
            show-icon
            style="margin-bottom: 10px"
          />
          <el-form label-position="top" :disabled="loading">
            <el-form-item label="Base URL">
              <el-input v-model="embedding.embedding_base_url" placeholder="https://api.openai.com/v1" />
            </el-form-item>
            <el-form-item label="API Key">
              <el-input v-model="embedding.embedding_api_key" type="password" show-password />
              <el-checkbox v-model="clearKeys.embedding" style="margin-top: 6px">
                清空已保存的 API Key
              </el-checkbox>
            </el-form-item>
            <el-form-item label="Embedding Model">
              <el-input v-model="embedding.embedding_model" placeholder="text-embedding-3-small" />
            </el-form-item>
          </el-form>
          <div class="toolbar" style="margin-bottom: 0">
            <el-button type="primary" :loading="saving.embedding" @click="save('embedding')">
              保存
            </el-button>
            <el-button :loading="testing.embedding" @click="test('embedding')">测试连接</el-button>
          </div>
          <el-alert
            v-if="testResults.embedding"
            :type="testResults.embedding.ok ? 'success' : 'error'"
            :title="testResults.embedding.text"
            :closable="false"
            show-icon
            style="margin-top: 12px"
          />
        </div>

        <div class="panel">
          <h2 class="panel-title">说明</h2>
          <div class="muted" style="font-size: 13px; line-height: 1.8">
            这里的配置是全局兜底：当 Agent 未绑定 LLM Profile 且没有默认 Profile 时生效。
            API Key 在服务端加密存储，读取接口只返回掩码；保存时留空（且未勾选清空）表示保留原值。
          </div>
        </div>
      </el-col>
    </el-row>

    <div class="panel">
      <h2 class="panel-title">CodeQL 引擎</h2>
      <el-alert
        v-if="codeqlResult"
        :type="codeqlResult.ok ? 'success' : 'error'"
        :title="codeqlResult.text"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      />
      <el-form label-position="top" :disabled="loading">
        <el-row :gutter="14">
          <el-col :xs="24" :sm="12">
            <el-form-item label="Binary（留空自动探测）">
              <el-input v-model="codeql.codeql_bin" placeholder="~/.codesentry/tools/codeql/codeql" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="Query packs 搜索路径">
              <el-input v-model="codeql.codeql_search_path" placeholder="~/.codeql/packages" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="Suite（支持 {lang}）">
              <el-input v-model="codeql.codeql_suite" placeholder="codeql/{lang}-queries:codeql-suites/{lang}-security-extended.qls" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="Build mode">
              <el-select v-model="codeql.codeql_build_mode" style="width: 100%">
                <el-option label="none" value="none" />
                <el-option label="autobuild" value="autobuild" />
                <el-option label="manual" value="manual" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="Timeout (s)">
              <el-input-number v-model="codeql.timeout" :min="60" :max="7200" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="18">
            <el-form-item label="Build command（仅 manual）">
              <el-input
                v-model="codeql.codeql_build_command"
                :disabled="codeql.codeql_build_mode !== 'manual'"
                placeholder="mvn -q -DskipTests package"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="6">
            <el-form-item label="DB cache">
              <el-switch v-model="codeql.cache" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="4">
            <el-form-item label="自动安装">
              <el-switch v-model="codeql.auto_install" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="4">
            <el-form-item label="许可确认">
              <el-switch v-model="codeql.license_ack" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="5">
            <el-form-item label="安装版本">
              <el-input v-model="codeql.version" placeholder="2.27.2" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="5">
            <el-form-item label="SHA256（可选）">
              <el-input v-model="codeql.sha256" placeholder="下载包校验和" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="安装目录（留空默认 work/tools/codeql）">
              <el-input v-model="codeql.install_dir" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <div class="toolbar" style="margin-bottom: 0">
        <el-button type="primary" :loading="codeqlSaving" @click="saveCodeql">保存</el-button>
        <el-button :loading="codeqlTesting" @click="testCodeql">探测</el-button>
        <el-button :loading="codeqlInstalling" @click="installCodeql">安装 / 更新</el-button>
        <span v-if="codeqlStatus?.found" class="muted">
          {{ codeqlStatus.version || '已安装' }} · {{ codeqlStatus.binary }}
        </span>
        <span v-else class="muted">未检测到 CodeQL（可填写 binary 或安装到默认目录）</span>
      </div>
    </div>

    <div class="panel">
      <div class="toolbar">
        <h2 class="panel-title" style="margin: 0">通知渠道</h2>
        <div class="grow" />
        <el-button size="small" :loading="hooksLoading" @click="loadNotifications">刷新</el-button>
      </div>
      <el-table :data="hooks" size="small" max-height="260">
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="name" label="名称" min-width="130" />
        <el-table-column prop="kind" label="类型" width="100" />
        <el-table-column prop="url" label="URL" min-width="220" show-overflow-tooltip />
        <el-table-column label="签名" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.has_secret ? 'success' : 'info'">
              {{ row.has_secret ? '有' : '无' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button link type="primary" @click="testHook(row)">测试</el-button>
            <el-button link type="danger" @click="removeHook(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty :image-size="50" description="还没有通知渠道" /></template>
      </el-table>
      <el-row :gutter="12" style="margin-top: 12px">
        <el-col :xs="24" :sm="6">
          <el-input v-model="hookForm.name" placeholder="名称" />
        </el-col>
        <el-col :xs="24" :sm="4">
          <el-select v-model="hookForm.kind" style="width: 100%">
            <el-option label="generic" value="generic" />
            <el-option label="飞书" value="feishu" />
            <el-option label="钉钉" value="dingtalk" />
            <el-option label="企业微信" value="wecom" />
            <el-option label="邮件" value="email" />
          </el-select>
        </el-col>
        <el-col :xs="24" :sm="7">
          <el-input v-model="hookForm.url" placeholder="https://...（邮件填 smtp）" />
        </el-col>
        <el-col :xs="24" :sm="3">
          <el-input v-model="hookForm.secret" type="password" placeholder="secret" />
        </el-col>
        <el-col :xs="24" :sm="4">
          <el-button type="primary" :loading="hookSaving" @click="addHook">新增</el-button>
        </el-col>
      </el-row>
      <div class="muted" style="font-size: 12px; margin-top: 6px">
        邮件渠道的收件人可在 headers.to 配置；未填则使用下方 SMTP 默认收件人。
      </div>
      <el-row :gutter="12" style="margin-top: 8px">
        <el-col :xs="24" :sm="16">
          <el-input v-model="hookForm.to" placeholder="邮件收件人（逗号分隔，可选）" />
        </el-col>
        <el-col :xs="24" :sm="8">
          <el-input v-model="hookForm.events" placeholder="事件，逗号分隔；* 表示全部" />
        </el-col>
      </el-row>
    </div>

    <div class="panel">
      <h2 class="panel-title">远程 PoC 目标（只读探测）</h2>
      <div class="toolbar">
        <el-switch v-model="poc.enabled" active-text="启用远程目标" />
        <el-switch v-model="poc.allow_private" active-text="允许私网" />
        <el-button size="small" type="primary" :loading="pocSaving" @click="savePoc">保存</el-button>
        <span class="muted">只做 GET/HEAD 探测，不执行 finding payload；默认关闭。</span>
      </div>
      <el-table :data="targets" size="small" max-height="220" style="margin-top: 10px">
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="name" label="名称" min-width="130" />
        <el-table-column prop="base_url" label="Base URL" min-width="220" show-overflow-tooltip />
        <el-table-column prop="allowed_hosts" label="允许 host" min-width="160" show-overflow-tooltip />
        <el-table-column prop="expires_at" label="过期" min-width="160" />
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button link type="primary" @click="probeTarget(row)">探测</el-button>
            <el-button link type="danger" @click="removeTarget(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-row :gutter="10" style="margin-top: 8px">
        <el-col :xs="24" :sm="4"><el-input v-model="targetForm.name" placeholder="名称" /></el-col>
        <el-col :xs="24" :sm="7"><el-input v-model="targetForm.base_url" placeholder="https://authorized.example" /></el-col>
        <el-col :xs="24" :sm="5"><el-input v-model="targetForm.allowed_hosts" placeholder="host1,host2" /></el-col>
        <el-col :xs="24" :sm="5"><el-input v-model="targetForm.expires_at" placeholder="过期 ISO8601（可选）" /></el-col>
        <el-col :xs="24" :sm="3"><el-button type="primary" @click="addTarget">新增</el-button></el-col>
      </el-row>
      <div v-if="pocResult" class="muted" style="font-size: 12px; margin-top: 6px">{{ pocResult }}</div>
    </div>

    <div class="panel">
      <h2 class="panel-title">SMTP 邮件</h2>
      <el-form label-position="top">
        <el-row :gutter="14">
          <el-col :xs="24" :sm="10">
            <el-form-item label="Host"><el-input v-model="smtp.smtp_host" /></el-form-item>
          </el-col>
          <el-col :xs="12" :sm="4">
            <el-form-item label="Port">
              <el-input v-model="smtp.smtp_port" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="4">
            <el-form-item label="TLS"><el-switch v-model="smtpTls" /></el-form-item>
          </el-col>
          <el-col :xs="24" :sm="6">
            <el-form-item label="User"><el-input v-model="smtp.smtp_user" /></el-form-item>
          </el-col>
          <el-col :xs="24" :sm="6">
            <el-form-item label="Password">
              <el-input v-model="smtp.smtp_password" type="password" show-password />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="6">
            <el-form-item label="From"><el-input v-model="smtp.smtp_from" /></el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="默认收件人"><el-input v-model="smtp.smtp_to" /></el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <div class="toolbar" style="margin-bottom: 0">
        <el-button type="primary" :loading="smtpSaving" @click="saveSmtp">保存</el-button>
        <el-button :loading="smtpTesting" @click="testSmtp">发送测试邮件</el-button>
        <span v-if="smtpResult" class="muted">{{ smtpResult }}</span>
      </div>
    </div>

    <div class="panel">
      <h2 class="panel-title">运维与配置</h2>
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="Work 目录">{{ disk.work_dir || '—' }}</el-descriptions-item>
        <el-descriptions-item label="占用">{{ disk.mb ?? 0 }} MB</el-descriptions-item>
        <el-descriptions-item label="文件数">{{ disk.files ?? 0 }}</el-descriptions-item>
      </el-descriptions>
      <div class="toolbar" style="margin-top: 12px; margin-bottom: 0">
        <el-input-number v-model="maintenance.days" :min="1" :max="3650" />
        <span class="muted">天前的扫描</span>
        <el-checkbox v-model="maintenance.clean_images">清理无引用目标镜像</el-checkbox>
        <el-button :loading="maintaining" @click="runMaintenance">立即维护</el-button>
        <div class="grow" />
        <el-button @click="exportConfig">导出配置</el-button>
        <el-select v-model="importMode" style="width: 110px">
          <el-option label="merge" value="merge" />
          <el-option label="replace" value="replace" />
        </el-select>
        <label class="el-button el-button--default">
          导入配置
          <input type="file" accept="application/json" hidden @change="importConfig" />
        </label>
      </div>
      <div v-if="maintenanceResult" class="muted" style="font-size: 12px; margin-top: 8px">
        {{ maintenanceResult }}
      </div>
      <div v-if="configResult" class="muted" style="font-size: 12px; margin-top: 8px">
        {{ configResult }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { api, errorMessage } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'

type Group = 'llm' | 'embedding'

interface LlmForm {
  model_base_url: string
  model_api_key: string
  fast_model: string
  deep_model: string
}

interface EmbeddingForm {
  embedding_base_url: string
  embedding_api_key: string
  embedding_model: string
}

const loading = ref(false)
const llm = reactive<LlmForm>({
  model_base_url: '',
  model_api_key: '',
  fast_model: '',
  deep_model: '',
})
const embedding = reactive<EmbeddingForm>({
  embedding_base_url: '',
  embedding_api_key: '',
  embedding_model: '',
})
const loadedValues = {
  llm: { ...llm } as Record<string, string>,
  embedding: { ...embedding } as Record<string, string>,
}
const clearKeys = reactive<Record<Group, boolean>>({ llm: false, embedding: false })
const errors = reactive<Record<Group, string>>({ llm: '', embedding: '' })
const saving = reactive<Record<Group, boolean>>({ llm: false, embedding: false })
const testing = reactive<Record<Group, boolean>>({ llm: false, embedding: false })
const testResults = reactive<Record<Group, { ok: boolean; text: string } | null>>({
  llm: null,
  embedding: null,
})
const codeql = reactive({
  codeql_bin: '',
  codeql_search_path: '',
  codeql_suite: '',
  codeql_build_mode: 'none',
  codeql_build_command: '',
  timeout: 1800,
  cache: true,
  auto_install: false,
  license_ack: false,
  version: '2.27.2',
  sha256: '',
  install_dir: '',
})
const codeqlSaving = ref(false)
const codeqlTesting = ref(false)
const codeqlInstalling = ref(false)
const codeqlResult = ref<{ ok: boolean; text: string } | null>(null)
const codeqlStatus = ref<Record<string, unknown> | null>(null)

interface HookRow {
  id: number
  name?: string
  kind?: string
  url?: string
  has_secret?: boolean
  events?: string[]
}

const hooks = ref<HookRow[]>([])
const hooksLoading = ref(false)
const hookSaving = ref(false)
const hookForm = reactive({ name: '', kind: 'generic', url: '', secret: '', to: '', events: '*' })
const smtp = reactive({
  smtp_host: '', smtp_port: '587', smtp_user: '', smtp_password: '',
  smtp_from: '', smtp_to: '',
})
const smtpTls = ref(true)
const smtpSaving = ref(false)
const smtpTesting = ref(false)
const smtpResult = ref('')
const disk = ref<Record<string, unknown>>({})
const maintenance = reactive({ days: 30, clean_images: false })
const maintaining = ref(false)
const maintenanceResult = ref('')
const importMode = ref('merge')
const configResult = ref('')
const poc = reactive({ enabled: false, allow_private: false })
const pocSaving = ref(false)
const pocResult = ref('')
const targets = ref<Array<Record<string, unknown>>>([])
const targetForm = reactive({ name: '', base_url: '', allowed_hosts: '', expires_at: '' })

async function loadGroup(group: Group): Promise<void> {
  errors[group] = ''
  try {
    const res = await api.get<Record<string, string>>(`/api/settings/${group}`)
    if (group === 'llm') {
      Object.assign(llm, {
        model_base_url: res.model_base_url ?? '',
        model_api_key: res.model_api_key ?? '',
        fast_model: res.fast_model ?? '',
        deep_model: res.deep_model ?? '',
      })
      loadedValues.llm = { ...llm }
    } else {
      Object.assign(embedding, {
        embedding_base_url: res.embedding_base_url ?? '',
        embedding_api_key: res.embedding_api_key ?? '',
        embedding_model: res.embedding_model ?? '',
      })
      loadedValues.embedding = { ...embedding }
    }
  } catch (e) {
    errors[group] = `加载 ${group} 设置失败：${errorMessage(e)}`
  }
}

async function load(): Promise<void> {
  loading.value = true
  await Promise.all([loadGroup('llm'), loadGroup('embedding'), loadCodeql(),
                     loadNotifications(), loadDisk()])
  loading.value = false
}

async function loadPoc(): Promise<void> {
  try {
    const [cfg, list] = await Promise.all([
      api.get<Record<string, string>>('/api/settings/poc'),
      api.get<{ targets?: Array<Record<string, unknown>> }>('/api/poc-targets'),
    ])
    poc.enabled = cfg.poc_remote_enabled === 'true'
    poc.allow_private = cfg.poc_remote_allow_private === 'true'
    targets.value = list.targets || []
  } catch {
    targets.value = []
  }
}

async function savePoc(): Promise<void> {
  pocSaving.value = true
  try {
    await api.put('/api/settings/poc', {
      values: {
        poc_remote_enabled: poc.enabled ? 'true' : 'false',
        poc_remote_allow_private: poc.allow_private ? 'true' : 'false',
      },
    })
    pocResult.value = '远程目标设置已保存'
  } catch (e) {
    pocResult.value = `保存失败：${errorMessage(e)}`
  } finally {
    pocSaving.value = false
  }
}

async function addTarget(): Promise<void> {
  try {
    await api.post('/api/poc-targets', {
      name: targetForm.name,
      base_url: targetForm.base_url,
      allowed_hosts: targetForm.allowed_hosts.split(',').map((x) => x.trim()).filter(Boolean),
      expires_at: targetForm.expires_at,
    })
    Object.assign(targetForm, { name: '', base_url: '', allowed_hosts: '', expires_at: '' })
    await loadPoc()
  } catch (e) {
    pocResult.value = `新增失败：${errorMessage(e)}`
  }
}

async function probeTarget(row: Record<string, unknown>): Promise<void> {
  try {
    const res = await api.post<Record<string, unknown>>(`/api/poc-targets/${row.id}/probe`)
    pocResult.value = `探测 #${row.id}：${JSON.stringify(res)}`
  } catch (e) {
    pocResult.value = `探测失败：${errorMessage(e)}`
  }
}

async function removeTarget(row: Record<string, unknown>): Promise<void> {
  try {
    await api.del(`/api/poc-targets/${row.id}`)
    await loadPoc()
  } catch (e) {
    pocResult.value = `删除失败：${errorMessage(e)}`
  }
}

async function loadNotifications(): Promise<void> {
  hooksLoading.value = true
  try {
    const [res, hooksRes] = await Promise.allSettled([
      api.get<Record<string, string>>('/api/settings/notifications'),
      api.get<{ webhooks?: HookRow[] }>('/api/webhooks'),
    ])
    if (res.status === 'fulfilled') {
      Object.assign(smtp, {
        smtp_host: res.value.smtp_host ?? '',
        smtp_port: res.value.smtp_port || '587',
        smtp_user: res.value.smtp_user ?? '',
        smtp_password: res.value.smtp_password ?? '',
        smtp_from: res.value.smtp_from ?? '',
        smtp_to: res.value.smtp_to ?? '',
      })
      smtpTls.value = (res.value.smtp_tls ?? 'true') !== 'false'
    }
    hooks.value = hooksRes.status === 'fulfilled' ? (hooksRes.value.webhooks || []) : []
  } finally {
    hooksLoading.value = false
  }
}

async function loadDisk(): Promise<void> {
  try {
    disk.value = await api.get<Record<string, unknown>>('/api/ops/disk')
  } catch {
    disk.value = {}
  }
}

async function addHook(): Promise<void> {
  hookSaving.value = true
  try {
    const headers: Record<string, string> = {}
    if (hookForm.kind === 'email' && hookForm.to.trim()) headers.to = hookForm.to.trim()
    const events = hookForm.events.split(',').map((x) => x.trim()).filter(Boolean)
    await api.post('/api/webhooks', {
      name: hookForm.name,
      kind: hookForm.kind,
      url: hookForm.kind === 'email' ? 'smtp' : hookForm.url,
      secret: hookForm.secret,
      events: events.length ? events : ['*'],
      headers,
    })
    ElMessage.success('通知渠道已创建')
    Object.assign(hookForm, { name: '', kind: 'generic', url: '', secret: '', to: '', events: '*' })
    await loadNotifications()
  } catch (e) {
    ElMessage.error(`创建失败：${errorMessage(e)}`)
  } finally {
    hookSaving.value = false
  }
}

async function testHook(row: HookRow): Promise<void> {
  try {
    const res = await api.post<{ ok?: boolean; error?: string }>(`/api/webhooks/${row.id}/test`)
    if (res.ok) ElMessage.success('测试通知已发送')
    else ElMessage.error(`发送失败：${res.error || '未知错误'}`)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function removeHook(row: HookRow): Promise<void> {
  try {
    await api.del(`/api/webhooks/${row.id}`)
    await loadNotifications()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function saveSmtp(): Promise<void> {
  smtpSaving.value = true
  smtpResult.value = ''
  try {
    await api.put('/api/settings/notifications', {
      values: {
        smtp_host: smtp.smtp_host,
        smtp_port: smtp.smtp_port,
        smtp_user: smtp.smtp_user,
        smtp_password: smtp.smtp_password,
        smtp_from: smtp.smtp_from,
        smtp_to: smtp.smtp_to,
        smtp_tls: smtpTls.value ? 'true' : 'false',
      },
    })
    ElMessage.success('SMTP 配置已保存')
    await loadNotifications()
  } catch (e) {
    smtpResult.value = `保存失败：${errorMessage(e)}`
  } finally {
    smtpSaving.value = false
  }
}

async function testSmtp(): Promise<void> {
  smtpTesting.value = true
  smtpResult.value = ''
  try {
    const res = await api.post<{ ok?: boolean; error?: string }>('/api/settings/notifications/test')
    smtpResult.value = res.ok ? '测试邮件已发送' : `发送失败：${res.error || ''}`
  } catch (e) {
    smtpResult.value = `测试失败：${errorMessage(e)}`
  } finally {
    smtpTesting.value = false
  }
}

async function runMaintenance(): Promise<void> {
  maintaining.value = true
  maintenanceResult.value = ''
  try {
    const res = await api.post<Record<string, unknown>>('/api/ops/maintenance', {
      days: maintenance.days,
      codeql_days: 7,
      orphan_days: 7,
      clean_images: maintenance.clean_images,
    })
    maintenanceResult.value = `清理完成：${JSON.stringify(res)}`
    await loadDisk()
  } catch (e) {
    maintenanceResult.value = `维护失败：${errorMessage(e)}`
  } finally {
    maintaining.value = false
  }
}

async function exportConfig(): Promise<void> {
  try {
    const doc = await api.get<Record<string, unknown>>('/api/config/export')
    const blob = new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'codesentry-config.json'
    a.click()
    URL.revokeObjectURL(url)
    configResult.value = '配置已导出（不含密钥）'
  } catch (e) {
    configResult.value = `导出失败：${errorMessage(e)}`
  }
}

async function importConfig(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    const doc = JSON.parse(await file.text()) as Record<string, unknown>
    const res = await api.post<{ ok?: boolean; counts?: unknown; errors?: string[] }>(
      '/api/config/import', { doc, mode: importMode.value },
    )
    configResult.value = res.ok
      ? `导入完成：${JSON.stringify(res.counts)}`
      : `导入有错误：${(res.errors || []).join('; ')}`
    await load()
  } catch (e) {
    configResult.value = `导入失败：${errorMessage(e)}`
  } finally {
    input.value = ''
  }
}

async function loadCodeql(): Promise<void> {
  try {
    const [cfg, status] = await Promise.allSettled([
      api.get<Record<string, string>>('/api/settings/codeql'),
      api.get<Record<string, unknown>>('/api/engines/codeql/status'),
    ])
    if (cfg.status === 'fulfilled') {
      Object.assign(codeql, {
        codeql_bin: cfg.value.codeql_bin ?? '',
        codeql_search_path: cfg.value.codeql_search_path ?? '',
        codeql_suite: cfg.value.codeql_suite ?? '',
        codeql_build_mode: cfg.value.codeql_build_mode || 'none',
        codeql_build_command: cfg.value.codeql_build_command ?? '',
        timeout: Number(cfg.value.codeql_timeout_s || 1800),
        cache: (cfg.value.codeql_db_cache ?? 'true') !== 'false',
        auto_install: (cfg.value.codeql_auto_install ?? 'false') === 'true',
        license_ack: (cfg.value.codeql_license_ack ?? 'false') === 'true',
        version: cfg.value.codeql_version || '2.27.2',
        sha256: cfg.value.codeql_sha256 ?? '',
        install_dir: cfg.value.codeql_install_dir ?? '',
      })
    }
    codeqlStatus.value = status.status === 'fulfilled' ? status.value : null
  } catch {
    codeqlStatus.value = null
  }
}

async function saveCodeql(): Promise<void> {
  codeqlSaving.value = true
  codeqlResult.value = null
  try {
    await api.put('/api/settings/codeql', {
      values: {
        codeql_bin: codeql.codeql_bin,
        codeql_search_path: codeql.codeql_search_path,
        codeql_suite: codeql.codeql_suite,
        codeql_build_mode: codeql.codeql_build_mode,
        codeql_build_command: codeql.codeql_build_command,
        codeql_timeout_s: String(codeql.timeout),
        codeql_db_cache: codeql.cache ? 'true' : 'false',
        codeql_auto_install: codeql.auto_install ? 'true' : 'false',
        codeql_license_ack: codeql.license_ack ? 'true' : 'false',
        codeql_version: codeql.version,
        codeql_sha256: codeql.sha256,
        codeql_install_dir: codeql.install_dir,
      },
    })
    ElMessage.success('CodeQL 配置已保存')
    await loadCodeql()
  } catch (e) {
    codeqlResult.value = { ok: false, text: `保存失败：${errorMessage(e)}` }
  } finally {
    codeqlSaving.value = false
  }
}

async function installCodeql(): Promise<void> {
  codeqlInstalling.value = true
  codeqlResult.value = null
  try {
    const res = await api.post<Record<string, unknown>>('/api/engines/codeql/install', {
      version: codeql.version, license_ack: codeql.license_ack, sha256: codeql.sha256,
    })
    codeqlResult.value = {
      ok: Boolean(res.ok),
      text: res.ok ? `安装完成：${res.binary}` : `安装失败：${String(res.error || '')}`,
    }
    if (res.ok) await loadCodeql()
  } catch (e) {
    codeqlResult.value = { ok: false, text: `安装失败：${errorMessage(e)}` }
  } finally {
    codeqlInstalling.value = false
  }
}

async function testCodeql(): Promise<void> {
  codeqlTesting.value = true
  codeqlResult.value = null
  try {
    const res = await api.post<Record<string, unknown>>('/api/engines/codeql/test')
    codeqlStatus.value = res
    codeqlResult.value = {
      ok: Boolean(res.ok),
      text: res.ok
        ? `CodeQL ${res.version || ''}，语言：${(res.languages as string[] || []).join(', ') || '—'}`
        : `未检测到：${String(res.error || res.binary || '')}`,
    }
  } catch (e) {
    codeqlResult.value = { ok: false, text: `探测失败：${errorMessage(e)}` }
  } finally {
    codeqlTesting.value = false
  }
}

function buildValues(group: Group): Record<string, string> {
  if (group === 'llm') {
    const values: Record<string, string> = {
      model_base_url: llm.model_base_url,
      fast_model: llm.fast_model,
      deep_model: llm.deep_model,
    }
    if (clearKeys.llm) values.model_api_key = ''
    else if (llm.model_api_key !== loadedValues.llm.model_api_key && llm.model_api_key) {
      values.model_api_key = llm.model_api_key
    }
    return values
  }
  const values: Record<string, string> = {
    embedding_base_url: embedding.embedding_base_url,
    embedding_model: embedding.embedding_model,
  }
  if (clearKeys.embedding) values.embedding_api_key = ''
  else if (
    embedding.embedding_api_key !== loadedValues.embedding.embedding_api_key &&
    embedding.embedding_api_key
  ) {
    values.embedding_api_key = embedding.embedding_api_key
  }
  return values
}

async function save(group: Group): Promise<void> {
  saving[group] = true
  errors[group] = ''
  try {
    await api.put(`/api/settings/${group}`, { values: buildValues(group) })
    ElMessage.success(`${group} 设置已保存`)
    clearKeys[group] = false
    await loadGroup(group)
  } catch (e) {
    errors[group] = `保存失败：${errorMessage(e)}`
  } finally {
    saving[group] = false
  }
}

async function test(group: Group): Promise<void> {
  testing[group] = true
  testResults[group] = null
  try {
    const res = await api.post<Record<string, unknown>>(`/api/settings/${group}/test`)
    const ok = res?.ok === true
    testResults[group] = {
      ok,
      text: ok
        ? `${group} 连接成功：${JSON.stringify(res)}`
        : `${group} 连接失败：${String(res?.error || JSON.stringify(res))}`,
    }
  } catch (e) {
    testResults[group] = { ok: false, text: `测试请求失败：${errorMessage(e)}` }
  } finally {
    testing[group] = false
  }
}

onMounted(load)
</script>
