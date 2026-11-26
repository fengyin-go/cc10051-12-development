<template>
  <section class="forensic-panel" data-testid="quality-execution-panel">
    <div class="panel-head">
      <div>
        <h3>规则执行轮与复算联动</h3>
        <p class="page-desc">
          质量规则库按复算导入接口关联的执行轮与检查记录重新运算；口径以报告版本冻结快照为准。
        </p>
      </div>
      <RouterLink class="btn primary" to="/recheck" data-testid="quality-rule-recheck-entry">
        复算入口
      </RouterLink>
    </div>

    <div class="correct-row" v-if="primary">
      <span>
        主执行轮 <strong>{{ primary.execution_no }}</strong>（{{ primary.execution_round || primary.执行轮 }}）：
        检查 {{ primary.检查总数 }} 条，当前命中
        <strong data-testid="execution-hits">{{ primary.命中数 }}</strong>
        <em v-if="primary.corrected" class="corrected-tag">已应用迟到更正</em>
      </span>
      <button
        class="btn warn"
        type="button"
        data-testid="rule-page-correct"
        :disabled="correcting || Boolean(primary.corrected)"
        @click="correct"
      >
        {{ primary.corrected ? '已更正为 2 命中 / 80%' : '规则执行更正（命中 1 → 2）' }}
      </button>
      <span v-if="message" class="correction-msg" role="status">{{ message }}</span>
    </div>

    <table class="data-table" data-testid="execution-list">
      <thead>
        <tr>
          <th>执行批次</th>
          <th>执行轮</th>
          <th>报告编号</th>
          <th>检查总数</th>
          <th>命中数</th>
          <th>状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in executions" :key="item.id" :data-testid="`execution-row-${item.id}`">
          <td>{{ item.execution_no || item.执行批次 }}</td>
          <td>{{ item.execution_round || item.执行轮 }}</td>
          <td>{{ item.report_no || item.报告编号 }}</td>
          <td>{{ item.检查总数 }}</td>
          <td>{{ item.命中数 }}</td>
          <td>{{ item.更正状态 || item.status }}</td>
          <td class="row-actions">
            <a class="link" :href="detailsExportUrl(item.id)" :data-testid="`execution-details-${item.id}`">
              明细导出
            </a>
            <RouterLink
              class="link"
              :to="{ path: '/recheck', query: { report_no: item.report_no, execution_id: String(item.id) } }"
            >复算</RouterLink>
          </td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import {
  correctExecution,
  detailsExportUrl,
  listExecutions,
  type ExecutionRow,
} from '@/api/forensic'

const executions = ref<ExecutionRow[]>([])
const correcting = ref(false)
const message = ref('')

const primary = ref<ExecutionRow | null>(null)

async function refresh() {
  try {
    executions.value = await listExecutions()
    primary.value = executions.value.find((e) => e.id === 1) || executions.value[0] || null
  } catch {
    executions.value = []
  }
}

async function correct() {
  if (!primary.value) return
  correcting.value = true
  message.value = ''
  try {
    const result = await correctExecution(primary.value.id, { hits: 2 })
    message.value = result?.message || '更正完成'
    await refresh()
  } catch (error) {
    message.value = error instanceof Error ? error.message : '更正失败'
  } finally {
    correcting.value = false
  }
}

onMounted(refresh)
</script>

<style scoped>
.forensic-panel { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; margin: 14px 0; }
.panel-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.panel-head h3 { margin: 0 0 4px; font-size: 16px; }
.correct-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; background: #fffaeb; border: 1px solid #fedf89; border-radius: 8px; padding: 10px 12px; margin: 12px 0; font-size: 13px; }
.btn.warn { background: #dc6803; border-color: #dc6803; color: #fff; }
.corrected-tag { color: #b54708; font-style: normal; margin-left: 6px; }
.correction-msg { color: #b54708; }
</style>
