<template>
  <section class="page" data-module="forensic-recheck">
    <header class="page-head">
      <div>
        <h2>取证复算入口</h2>
        <p class="page-desc">
          上传取证文件后，按文件内的报告编号打开对应规则执行轮，分开呈现原结果与独立重算；
          报告版本无效或文件不属于该次执行时会明确拒绝，可换回原文件重新上传。
        </p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn" to="/quality_result">返回质量报告</RouterLink>
      </div>
    </header>

    <RecheckPanel
      :scope-report-no="scopeReportNo"
      :scope-execution-id="scopeExecutionId"
    />

    <section class="forensic-panel" data-testid="batch-history">
      <h3>本报告复算批次 / 取证记录</h3>
      <p class="page-desc">同一取证包重复导入不会新增检查数；每个复算批次内原结果与重算固定为同一报告版本的同一口径分数，不会混用两种口径。</p>
      <table class="data-table">
        <thead>
          <tr>
            <th>复算批次</th>
            <th>报告编号</th>
            <th>版本</th>
            <th>执行轮</th>
            <th>检查数</th>
            <th>命中数</th>
            <th>复算评分</th>
            <th>结论</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="batch in batches" :key="String(batch.id || batch.batch_no)">
            <td>{{ batch.batch_no }}</td>
            <td>{{ batch.report_no }}</td>
            <td>{{ batch.report_version }}</td>
            <td>{{ batch.execution_round }}</td>
            <td>{{ batch.check_count }}</td>
            <td>{{ batch.hits }}</td>
            <td data-testid="batch-score">{{ batch.score }}</td>
            <td>{{ batch.consistent ? '一致' : '不一致' }}</td>
          </tr>
          <tr v-if="!batches.length">
            <td colspan="8" class="empty-state">尚未导入取证包</td>
          </tr>
        </tbody>
      </table>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import RecheckPanel from '@/components/RecheckPanel.vue'
import { apiUrl } from '@/api/forensic'

type Batch = {
  id?: number
  batch_no?: string
  report_no?: string
  report_version?: string
  execution_round?: string
  check_count?: number
  hits?: number
  score?: string
  consistent?: boolean
}

const route = useRoute()
const batches = ref<Batch[]>([])

const scopeReportNo = computed(() => String(route.query.report_no || ''))
const scopeExecutionId = computed(() => String(route.query.execution_id || ''))

async function loadBatches() {
  try {
    const query = scopeReportNo.value
      ? `?report_no=${encodeURIComponent(scopeReportNo.value)}`
      : ''
    const response = await fetch(apiUrl(`/api/forensic/recheck/batches${query}`))
    if (!response.ok) return
    const data = await response.json()
    batches.value = data.items ?? []
  } catch {
    batches.value = []
  }
}

onMounted(loadBatches)
watch(() => route.query.report_no, loadBatches)
</script>

<style scoped>
.forensic-panel { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; margin: 14px 0; }
.forensic-panel h3 { margin: 0 0 6px; font-size: 16px; }
</style>
