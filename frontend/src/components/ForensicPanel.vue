<template>
  <section class="forensic-panel" data-testid="forensic-panel">
    <div class="panel-top">
      <div>
        <h3>取证申请与复算入口</h3>
        <p class="page-desc">
          取证申请受理时由服务端绑定具体规则执行轮与报告版本，下载前即可核对取证编号与所依据的报告结果。
        </p>
      </div>
      <div class="panel-actions">
        <button class="btn primary" type="button" data-testid="forensic-apply-btn" @click="openCreate()">
          新增取证申请
        </button>
      </div>
    </div>

    <div class="correction-card" data-testid="correction-card">
      <div class="correction-text">
        <strong>迟到的规则执行更正</strong>
        <span>
          主场景执行批次 EXEC-20261120-01：10 条检查中原命中 1（90%），
          更正后命中 2（80%）。已受理的取证申请仍绑定原报告版本，不受更正影响。
        </span>
      </div>
      <button
        class="btn warn"
        type="button"
        data-testid="rule-execution-correct"
        :disabled="correcting || primaryCorrected"
        @click="applyCorrection"
      >
        {{ correcting ? '更正中…' : correctionButtonText }}
      </button>
      <span v-if="correctionMessage" class="correction-msg" data-testid="correction-message">
        {{ correctionMessage }}
      </span>
    </div>

    <table class="data-table forensic-table" data-testid="forensic-applications">
      <thead>
        <tr>
          <th>取证编号</th>
          <th>报告编号 / 版本</th>
          <th>规则执行 / 执行轮</th>
          <th>所依据的报告结果</th>
          <th>申请状态</th>
          <th>文件操作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="app in applications"
          :key="app.id"
          :data-testid="`application-row-${app.id}`"
          :data-evidence-no="app.evidence_no || app.取证编号"
        >
          <td>
            <span
              class="evidence-no"
              :data-testid="app.id === 1 ? 'evidence-no' : `evidence-no-${app.id}`"
            >
              {{ app.evidence_no || app.取证编号 }}
            </span>
          </td>
          <td>
            <span :data-testid="`app-report-no-${app.id}`">{{ app.report_no || app.报告编号 }}</span>
            <span class="version-tag" :data-testid="`app-report-version-${app.id}`">
              {{ app.report_version || app.报告版本 }}
            </span>
          </td>
          <td>
            #{{ app.execution_id }} {{ app.execution_no }}
            <span class="round-tag">{{ app.execution_round || app.执行轮 }}</span>
          </td>
          <td :data-testid="`app-basis-${app.id}`">{{ app.所依据的报告结果 || basisFallback(app) }}</td>
          <td>
            <span class="status-tag" :data-testid="`app-status-${app.id}`">{{ app.申请状态 || app.status }}</span>
            <span class="download-state">{{ app.download_status || '未下载' }}</span>
          </td>
          <td class="row-actions">
            <a
              class="link"
              :href="forensicDownloadUrl(app.id)"
              :download="`forensic-${app.evidence_no || app.取证编号}.json`"
              :data-testid="`download-forensic-${app.id}`"
              data-action="download-forensic"
            >{{ app.id === 1 ? '下载取证文件' : '下载备用取证包' }}</a>
            <a
              class="link"
              :href="detailsExportUrl(app.execution_id || app.id)"
              :data-testid="`details-export-${app.id}`"
            >明细导出</a>
            <RouterLink
              class="link"
              :to="recheckLink(app)"
              :data-testid="`goto-recheck-${app.id}`"
            >复算导入</RouterLink>
          </td>
        </tr>
        <tr v-if="!applications.length">
          <td colspan="6" class="empty-state">暂无取证申请，可点击「新增取证申请」</td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="forensic-create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>新增取证申请</h3>
        <p class="page-desc">受理后服务端将绑定所选报告版本及其规则执行轮并冻结口径。</p>
        <label class="create-field">
          <span>质量报告</span>
          <select v-model="createValues.report_id" data-testid="forensic-report-select">
            <option v-for="report in reportOptions" :key="report.id" :value="String(report.id)">
              {{ report.报告批次 || report.报告编号 }}（{{ report.检查总数 }} 条 / 命中 {{ report.命中数 }} / {{ report.评分结果 }}）
            </option>
          </select>
        </label>
        <label class="create-field">
          <span>绑定报告版本</span>
          <select v-model="createValues.report_version" data-testid="forensic-version-select">
            <option value="">默认已审批版本（v1 / 90%）</option>
            <option value="v1">v1（原审批结果 90%）</option>
            <option value="v2">v2（更正后结果 80%）</option>
          </select>
        </label>
        <label class="create-field">
          <span>申请人</span>
          <input v-model="createValues.applicant" data-testid="forensic-applicant" placeholder="核算同事姓名" />
        </label>
        <label class="create-field">
          <span>申请事项</span>
          <input v-model="createValues.reason" data-testid="forensic-reason" placeholder="例如：年度审计取证复算" />
        </label>
        <p v-if="createError" class="error-text" data-testid="forensic-create-error">{{ createError }}</p>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" type="submit" data-testid="submit-forensic-apply" :disabled="creating">
            {{ creating ? '受理中…' : '确认申请并受理' }}
          </button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { listEntries } from '@/api/backend-service'
import {
  correctExecution,
  createApplication,
  detailsExportUrl,
  forensicDownloadUrl,
  listApplications,
  type ForensicApplication,
} from '@/api/forensic'
import type { EntryRow } from '@/data/types'

const emit = defineEmits<{ (event: 'changed'): void }>()

const applications = ref<ForensicApplication[]>([])
const reports = ref<EntryRow[]>([])
const showCreate = ref(false)
const creating = ref(false)
const createError = ref('')
const createValues = ref<Record<string, string>>({
  report_id: '4',
  report_version: '',
  applicant: '',
  reason: '',
})

const correcting = ref(false)
const primaryCorrected = ref(false)
const correctionMessage = ref('')

const reportOptions = computed(() =>
  reports.value.filter((r) => /QR-|质量报告样例/.test(String(r.报告批次 || '')) || Number(r.id) >= 4),
)

const correctionButtonText = computed(() =>
  primaryCorrected.value ? '已更正为命中 2 / 80%' : '规则执行更正（命中 1 → 2）',
)

function basisFallback(app: ForensicApplication): string {
  if (app.basis_total === undefined) return '—'
  return `${app.basis_total} 条检查 / 命中 ${app.basis_hits} / 评分 ${app.basis_score}`
}

function recheckLink(app: ForensicApplication): { path: string; query: Record<string, string> } {
  return {
    path: '/recheck',
    query: {
      report_no: String(app.report_no || app.报告编号 || ''),
      execution_id: String(app.execution_id || ''),
      application: String(app.id),
    },
  }
}

async function refresh() {
  try {
    applications.value = await listApplications()
  } catch {
    applications.value = []
  }
}

async function loadReports() {
  try {
    const page = await listEntries('quality_result', { size: '200' })
    reports.value = page.items
  } catch {
    reports.value = []
  }
}

function openCreate(presetReportId?: number | string) {
  createError.value = ''
  if (presetReportId !== undefined) {
    createValues.value.report_id = String(presetReportId)
  }
  showCreate.value = true
}

defineExpose({ openCreate, refresh })

async function submitCreate() {
  creating.value = true
  createError.value = ''
  try {
    const payload: Record<string, unknown> = { ...createValues.value }
    if (!payload.report_version) delete payload.report_version
    const result = await createApplication(payload)
    if (result.ok === false) throw new Error(result.message || '取证申请失败')
    showCreate.value = false
    await refresh()
    emit('changed')
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '取证申请失败'
  } finally {
    creating.value = false
  }
}

async function applyCorrection() {
  correcting.value = true
  correctionMessage.value = ''
  try {
    const result = await correctExecution(1, { hits: 2 })
    primaryCorrected.value = true
    correctionMessage.value = result?.message || '已更正：10 条中命中 2，评分 80%'
    await refresh()
    emit('changed')
  } catch (error) {
    correctionMessage.value = error instanceof Error ? error.message : '更正失败'
  } finally {
    correcting.value = false
  }
}

onMounted(() => {
  void refresh()
  void loadReports()
})
</script>

<style scoped>
.forensic-panel { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; margin: 14px 0; }
.panel-top { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; flex-wrap: wrap; }
.panel-top h3 { margin: 0 0 4px; font-size: 16px; }
.panel-actions { display: flex; gap: 8px; }
.correction-card {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  background: #fffaeb; border: 1px solid #fedf89; border-radius: 8px; padding: 10px 12px; margin: 12px 0;
}
.correction-text { display: flex; flex-direction: column; gap: 2px; font-size: 13px; flex: 1; min-width: 260px; }
.btn.warn { background: #dc6803; border-color: #dc6803; color: #fff; }
.correction-msg { color: #b54708; font-size: 13px; }
.forensic-table { margin-top: 8px; }
.evidence-no { font-family: ui-monospace, Menlo, monospace; font-weight: 600; }
.version-tag, .round-tag {
  display: inline-block; margin-left: 6px; padding: 0 6px; border-radius: 4px;
  background: #eef2ff; color: #3538cd; font-size: 12px;
}
.round-tag { background: #ecfdf3; color: #067647; }
.status-tag { color: #067647; }
.download-state { display: block; color: var(--muted); font-size: 12px; }
.row-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.create-field select, .create-field input {
  width: 100%; border: 1px solid var(--border); border-radius: 6px; padding: 8px;
}
</style>
