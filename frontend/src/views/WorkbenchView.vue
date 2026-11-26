<template>
  <section v-if="meta" class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">
          登记{{ meta.entity }}
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">
          导出{{ meta.name }}清单
        </button>
        <RouterLink
          v-if="meta.key === 'quality_result'"
          class="btn"
          data-testid="recheck-entry"
          to="/recheck"
        >
          复算入口
        </RouterLink>
      </div>
    </header>

    <ForensicPanel
      v-if="meta.key === 'quality_result'"
      ref="forensicPanelRef"
      @changed="reload"
    />
    <RecheckPanel v-if="meta.key === 'quality_result'" />
    <QualityRulePanel v-if="meta.key === 'quality_rule'" />

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status }}</td>
          <td class="row-actions">
            <button
              v-for="action in meta.actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <template v-if="meta.key === 'quality_result'">
              <a
                class="link"
                :href="summaryDownloadUrl(Number(row.id))"
                :data-testid="`action-${row.id}-下载摘要`"
                data-action="download-summary"
              >下载摘要</a>
              <button
                class="link"
                type="button"
                :data-testid="`action-${row.id}-取证申请`"
                @click="openForensicApply(Number(row.id))"
              >取证申请</button>
            </template>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + 2" class="empty-state">
            暂无{{ meta.name }}数据，可先登记{{ meta.entity }}
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in meta.fields" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>

  <section v-else class="page unknown-module" data-testid="unknown-module">
    <header class="page-head">
      <div>
        <h2>未登记的业务模块：{{ moduleKey }}</h2>
        <p class="page-desc">该地址没有对应的工作台，可前往取证复算入口上传取证文件。</p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn primary" to="/recheck">取证复算入口</RouterLink>
        <RouterLink class="btn" to="/quality_result">返回质量报告</RouterLink>
      </div>
    </header>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import ForensicPanel from '@/components/ForensicPanel.vue'
import QualityRulePanel from '@/components/QualityRulePanel.vue'
import RecheckPanel from '@/components/RecheckPanel.vue'
import {
  createEntry,
  downloadEntries,
  listEntries,
  runAction as applyAction,
} from '@/api/backend-service'
import { summaryDownloadUrl } from '@/api/forensic'
import { MODULE_BY_KEY } from '@/data/modules'
import type { EntryRow } from '@/data/types'

const props = defineProps<{ moduleKey: string }>()
const meta = computed(() => MODULE_BY_KEY.get(props.moduleKey))
const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = computed(() => meta.value?.fields.slice(0, 3) ?? [])
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const forensicPanelRef = ref<InstanceType<typeof ForensicPanel> | null>(null)

function openForensicApply(reportId: number) {
  forensicPanelRef.value?.openCreate(reportId)
  forensicPanelRef.value &&
    (document.querySelector('[data-testid="forensic-panel"]') as HTMLElement | null)
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
const stats = computed(() => {
  const current = meta.value
  if (!current) return []
  return [
    { label: current.metrics[0], value: total.value },
    { label: current.metrics[1], value: rows.value.filter((row) => row.status === current.statuses[1]).length },
    {
      label: current.metrics[2],
      value: rows.value.filter((row) => row.status === current.statuses[current.statuses.length - 1]).length,
    },
  ]
})
const statusSummary = computed(() => {
  const current = meta.value
  if (!current) return []
  return current.statuses.map((status) => ({
    status,
    count: rows.value.filter((row) => String(row.status) === status).length,
  }))
})

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  if (!meta.value) return
  errorMessage.value = ''
  try {
    await downloadEntries(meta.value.key, filters.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  if (!meta.value) return
  createValues.value = Object.fromEntries(meta.value.fields.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  if (!meta.value) return
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await createEntry(meta.value.key, createValues.value)
    if (!result.ok) throw new Error(result.message)
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: EntryRow) {
  if (!meta.value) return
  errorMessage.value = ''
  try {
    const result = await applyAction(meta.value.key, Number(row.id), action)
    if (!result.ok) throw new Error(result.message)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

async function reload() {
  if (!meta.value) return
  errorMessage.value = ''
  try {
    const payload = await listEntries(meta.value.key, filters.value)
    rows.value = payload.items
    total.value = payload.total
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '业务列表读取失败'
  }
}

onMounted(() => {
  if (meta.value) void reload()
})
</script>
