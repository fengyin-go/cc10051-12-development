<template>
  <section class="forensic-panel recheck-panel" data-testid="recheck-panel">
    <header class="forensic-head">
      <h3>复算导入</h3>
      <p class="page-desc">
        上传核算同事的取证 JSON 包，系统按包内冻结的报告版本与规则口径，
        联动质量规则库对应执行轮的检查记录独立重算。
      </p>
    </header>

    <div
      v-if="scopeReportNo || scopeExecutionId"
      class="scope-banner"
      data-testid="recheck-scope"
    >
      当前复算入口绑定：
      <span v-if="scopeReportNo">报告编号 <strong>{{ scopeReportNo }}</strong></span>
      <span v-if="scopeExecutionId">规则执行 #<strong>{{ scopeExecutionId }}</strong></span>
      <span>；上传其他执行的取证文件将被拒绝。</span>
    </div>

    <div class="upload-row">
      <input
        ref="fileInput"
        type="file"
        id="forensic-file-input"
        name="file"
        data-testid="forensic-file-input"
        data-cy="file-input"
        aria-label="上传取证文件"
        accept=".json,application/json"
        class="file-input"
        @change="onFileChange"
      />
      <button
        class="btn primary"
        type="button"
        data-testid="choose-file"
        @click="triggerChoose"
      >
        上传取证文件
      </button>
      <button
        class="btn"
        type="button"
        data-testid="submit-recheck"
        :disabled="importing || !selectedText"
        @click="submitSelected"
      >
        {{ importing ? '复算中…' : '复算导入' }}
      </button>
      <button
        v-if="selectedFileName"
        class="btn ghost"
        type="button"
        data-testid="reselect-file"
        @click="triggerChoose"
      >
        换回原文件
      </button>
      <span v-if="selectedFileName" class="selected-file" data-testid="selected-file-name">
        {{ selectedFileName }}
      </span>
    </div>

    <div
      v-if="errorMessage"
      class="upload-error"
      role="alert"
      data-testid="upload-error"
    >
      <strong>上传错误：</strong><span>{{ errorMessage }}</span>
    </div>

    <div v-if="result" class="recheck-result" data-testid="recheck-result">
      <div class="result-meta">
        <h4>复算批次 <span data-testid="recheck-batch-no">{{ result.batch_no || result.复算批次 }}</span></h4>
        <dl class="meta-grid">
          <div><dt>文件引用报告编号</dt><dd data-testid="recheck-report-no"><span data-testid="report-no">{{ result.report_no || result.报告编号 }}</span></dd></div>
          <div><dt>报告版本</dt><dd data-testid="recheck-report-version"><span data-testid="report-version">{{ result.report_version || result.报告版本 }}</span></dd></div>
          <div><dt>对应规则执行</dt><dd data-testid="recheck-execution">
            #{{ result.execution_id }} {{ result.execution_no }}（执行轮 {{ result.execution_round || result.执行轮 }}）
          </dd></div>
          <div><dt>口径一致性</dt><dd :class="result.consistent ? 'ok-text' : 'error-text'" data-testid="recheck-consistent">
            {{ result.consistent ? '原结果与重算一致' : '原结果与重算不一致' }}
          </dd></div>
          <div><dt>本批检查数</dt><dd data-testid="batch-check-count">{{ result.check_count ?? result.检查数 ?? result.total }}</dd></div>
          <div><dt>命中数</dt><dd data-testid="batch-hit-count">{{ result.hits }}</dd></div>
        </dl>
      </div>

      <div
        v-if="result.duplicate"
        class="duplicate-notice"
        data-testid="duplicate-notice"
      >
        该取证包已导入过：同一检查记录不重复计数，本批检查数保持
        <strong>{{ result.check_count ?? result.检查数 }}</strong> 条不变。
      </div>

      <div class="score-compare">
        <article class="score-box original" data-testid="original-result">
          <h5>原结果（报告记录）</h5>
          <strong class="score" data-testid="original-score">
            <span data-testid="original_score">{{ originalScore }}</span>
          </strong>
          <p>检查 {{ originalTotal }} 条 · 命中 {{ originalHits }} 条</p>
        </article>
        <article class="score-box recalc" data-testid="recalculated-result">
          <h5>重算结果 · 实际重算分数（按文件口径独立运算）</h5>
          <strong class="score" data-testid="recalculated-score">
            <span data-testid="recalc-score"><span data-testid="recheck-score">{{ recalcScore }}</span></span>
          </strong>
          <p>检查 {{ result.check_count ?? result.total }} 条 · 命中 {{ result.hits }} 条</p>
        </article>
      </div>

      <div class="checks-wrap" data-testid="recheck-checks">
        <h5>执行轮检查记录（同一条记录在包内仅一次）</h5>
        <table class="data-table">
          <thead>
            <tr>
              <th>检查记录编号</th>
              <th>记录编号</th>
              <th>检查维度</th>
              <th>检查值</th>
              <th>原判定</th>
              <th>重算判定</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="check in checks" :key="String(check.check_id || check.检查记录编号)">
              <td>{{ check.check_id || check.检查记录编号 }}</td>
              <td>{{ check.记录编号 || '—' }}</td>
              <td>{{ check.检查维度 || '—' }}</td>
              <td>{{ check.检查值 === '' ? '（空）' : (check.检查值 ?? check.value ?? '—') }}</td>
              <td>{{ check.是否命中 || (check.hit ? '是' : '否') }}</td>
              <td>{{ check.重算是否命中 || (check.recalculated_hit ? '是' : '否') }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  importForensicPackage,
  type ForensicCheck,
  type RecheckResult,
} from '@/api/forensic'

const props = defineProps<{
  scopeReportNo?: string
  scopeExecutionId?: string
}>()

const router = useRouter()
const route = useRoute()

const fileInput = ref<HTMLInputElement | null>(null)
const selectedText = ref('')
const selectedFileName = ref('')
const selectedObject = ref<unknown>(null)
const importing = ref(false)
const errorMessage = ref('')
const result = ref<RecheckResult | null>(null)

const checks = computed<ForensicCheck[]>(() => {
  if (!result.value) return []
  return (
    result.value.batch?.checks ||
    result.value.checks ||
    []
  ) as ForensicCheck[]
})

const originalScore = computed(
  () => result.value?.original?.score || result.value?.原结果?.score || '—',
)
const recalcScore = computed(
  () => result.value?.recalculated?.score || result.value?.score || '—',
)
const originalTotal = computed(
  () => result.value?.original?.total ?? result.value?.total ?? '—',
)
const originalHits = computed(
  () => result.value?.original?.hits ?? result.value?.hits ?? '—',
)

function triggerChoose() {
  errorMessage.value = ''
  fileInput.value?.click()
}

async function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  selectedFileName.value = file.name
  const text = await file.text()
  selectedText.value = text
  // 清空原生 input 的值，保证再次选择/注入同一个文件也会重新触发 change，
  // 从而支持“重新导入同一包”的幂等校验。
  input.value = ''
  try {
    selectedObject.value = JSON.parse(text)
  } catch {
    selectedObject.value = null
    errorMessage.value = '取证文件不是有效的 JSON 包，请换回原始取证文件。'
    result.value = null
    return
  }
  // 选择后自动导入一次，满足“上传后即出复算结果”。
  await submitSelected()
}

async function submitSelected() {
  if (!selectedText.value) {
    errorMessage.value = '请先选择取证文件。'
    return
  }
  let packageObject = selectedObject.value
  if (packageObject === null) {
    try {
      packageObject = JSON.parse(selectedText.value)
    } catch {
      errorMessage.value = '取证文件无法解析，请上传本平台导出的 JSON 取证包。'
      return
    }
  }
  importing.value = true
  // 每次新的导入尝试清掉旧错误；失败时展示并保留本次错误，文件仍可重选。
  errorMessage.value = ''
  try {
    const response = await importForensicPackage(packageObject, {
      reportNo: props.scopeReportNo,
      executionId: props.scopeExecutionId,
    })
    result.value = response
    // 复算页按文件里的报告编号“打开”对应规则执行：把报告/执行同步到当前地址栏。
    if (response.report_no || response.execution_id) {
      await router.replace({
        path: route.path,
        query: {
          ...route.query,
          report_no: response.report_no || response.报告编号 || '',
          execution_id: response.execution_id ? String(response.execution_id) : '',
        },
      }).catch(() => undefined)
    }
  } catch (error) {
    result.value = null
    errorMessage.value = error instanceof Error ? error.message : '复算导入失败'
  } finally {
    importing.value = false
  }
}
</script>

<style scoped>
.forensic-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  margin: 14px 0;
}
.forensic-head h3 { margin: 0 0 4px; font-size: 16px; }
.upload-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 12px 0; }
.file-input { max-width: 260px; font-size: 12px; }
.selected-file { color: var(--muted); font-size: 13px; }
.upload-error {
  background: #fef3f2;
  border: 1px solid #fda29b;
  color: #b42318;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 13px;
  margin: 8px 0;
}
.scope-banner {
  background: #eff8ff;
  border: 1px solid #b2ddff;
  color: #1849a9;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
  margin-bottom: 10px;
}
.recheck-result { margin-top: 12px; border-top: 1px dashed var(--border); padding-top: 12px; }
.result-meta h4 { margin: 0 0 8px; }
.meta-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 16px; margin: 0 0 10px; }
.meta-grid dt { font-size: 12px; color: var(--muted); }
.meta-grid dd { margin: 2px 0 0; font-size: 13px; }
.ok-text { color: #067647; }
.duplicate-notice {
  background: #fffaeb; border: 1px solid #fedf89; color: #b54708;
  border-radius: 8px; padding: 8px 12px; font-size: 13px; margin: 8px 0;
}
.score-compare { display: flex; gap: 12px; margin: 12px 0; flex-wrap: wrap; }
.score-box {
  flex: 1; min-width: 220px; border: 1px solid var(--border);
  border-radius: 10px; padding: 12px 14px; background: #fafbfc;
}
.score-box h5 { margin: 0 0 6px; font-size: 13px; color: var(--muted); }
.score-box .score { font-size: 30px; color: #1f2937; }
.score-box p { margin: 6px 0 0; font-size: 12px; color: var(--muted); }
.score-box.recalc { border-color: #abefc6; background: #ecfdf3; }
.checks-wrap { margin-top: 10px; overflow-x: auto; }
.checks-wrap h5 { margin: 0 0 8px; }
</style>
