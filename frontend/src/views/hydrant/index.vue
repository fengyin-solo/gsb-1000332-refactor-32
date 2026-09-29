<template>
  <section class="page" data-module="hydrant">
    <header class="page-head">
      <div>
        <h2>消防栓管理</h2>
        <p class="page-desc">围绕消防栓编号、口径规格、所在道路、出水压力做全生命周期登记、检测、维修、拆除与维护记录追踪。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记消防栓</button>
        <button class="btn" type="button" @click="exportRows">导出消防栓清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <label class="filter-item">
        <span>设施状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <span>{{ displayValue(row, column) }}</span>
            <ul v-if="warnings(row).length" class="inline-warnings">
              <li v-for="warning in warnings(row)" :key="warning">{{ warning }}</li>
            </ul>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">查看详情</button>
            <button
              v-for="action in rowActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!rowActions(row).length" class="muted-text">无可用维护动作</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无消防栓数据，可先登记消防栓</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条消防栓记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="formVisible" class="modal-mask" @click.self="closeForm">
      <form class="modal" @submit.prevent="submitForm">
        <h3>{{ formTitle }}</h3>
        <label v-for="field in formFields" :key="field" class="form-item">
          <span>{{ field }}</span>
          <input v-model="formValues[field]" :placeholder="fieldPrompt(field)" />
        </label>
        <p v-if="formError" class="error-text">{{ formError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="closeForm">取消</button>
          <button class="btn primary" type="submit">保存</button>
        </div>
      </form>
    </div>

    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <article class="modal detail-modal">
        <header class="detail-head">
          <h3>消防栓详情 · {{ detail['消防栓编号'] }}</h3>
          <button class="btn" type="button" @click="detail = null">关闭</button>
        </header>

        <dl class="detail-grid">
          <template v-for="field in detailFields" :key="field">
            <dt>{{ field }}</dt>
            <dd>{{ displayValue(detail, field) }}</dd>
          </template>
          <dt>生命周期判断</dt>
          <dd>
            <strong>{{ detail.status }}</strong>
            <span v-if="detail.pending" class="tag">待处理</span>
            <span v-if="detail.abnormal" class="tag warning">异常</span>
            <span v-if="detail.incomplete" class="tag">缺字段</span>
          </dd>
        </dl>

        <ul v-if="warnings(detail).length" class="warning-list">
          <li v-for="warning in warnings(detail)" :key="warning">{{ warning }}</li>
        </ul>

        <div class="detail-actions">
          <button
            v-for="action in rowActions(detail)"
            :key="action"
            class="btn"
            type="button"
            @click="runAction(action, detail)"
          >
            {{ action }}
          </button>
          <span v-if="!rowActions(detail).length" class="muted-text">当前生命周期没有可继续执行的维护动作</span>
        </div>

        <h4>维护记录</h4>
        <table class="record-table">
          <thead>
            <tr>
              <th>#</th>
              <th>动作</th>
              <th>结果状态</th>
              <th>压力</th>
              <th>试水日期</th>
              <th>来源/备注</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="record in maintenanceRecords" :key="String(record.id)">
              <td>{{ record.id }}</td>
              <td>
                {{ record.action || '历史记录' }}
                <span v-if="record.duplicate" class="tag warning">重复维护</span>
              </td>
              <td>{{ record.status ?? '—' }}</td>
              <td>{{ formatPressure(record.pressure) }}</td>
              <td>{{ record.test_date || record.date || '—' }}</td>
              <td>{{ record.remark || record.source || 'system' }}</td>
            </tr>
            <tr v-if="!maintenanceRecords.length">
              <td colspan="6" class="empty-state">暂无维护记录</td>
            </tr>
          </tbody>
        </table>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, unknown>
type MaintenanceRecord = Record<string, string | number | null>

const ENDPOINT = '/api/hydrant'
const columns = ['消防栓编号', '口径规格', '所在道路', '出水压力', '上次试水日', '维护单位', '设施状态']
const detailFields = [...columns, '完好情况']
const statuses = ['待建档', '完好', '待维修', '锈蚀', '无水', '已拆除']
const createFields = ['消防栓编号', '口径规格', '所在道路', '出水压力', '上次试水日', '维护单位']
const completeFields = ['消防栓编号', '口径规格', '所在道路', '出水压力', '上次试水日', '维护单位']
const testFields = ['出水压力', '上次试水日', '维护单位']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({ 消防栓编号: '', 口径规格: '', 所在道路: '', status: '' })
const filterFields = ['消防栓编号', '口径规格', '所在道路']
const detail = ref<Row | null>(null)
const maintenanceRecords = ref<MaintenanceRecord[]>([])
const formVisible = ref(false)
const formMode = ref<'create' | 'complete' | 'test'>('create')
const formError = ref('')
const formTarget = ref<Row | null>(null)
const formValues = ref<Record<string, string>>({})

const stats = computed(() => {
  const count = (status: string) => rows.value.filter((row) => row.status === status).length
  return [
    { label: '完好消防栓', value: count('完好') },
    { label: '待维修消防栓', value: count('待维修') },
    { label: '锈蚀/无水', value: count('锈蚀') + count('无水') },
    { label: '待补档案', value: count('待建档') },
  ]
})

const formTitle = computed(() => {
  if (formMode.value === 'create') return '登记消防栓'
  if (formMode.value === 'complete') return '补全消防栓档案'
  return '消防栓试水检测'
})
const formFields = computed(() => {
  if (formMode.value === 'test') return testFields
  if (formMode.value === 'complete') return completeFields
  return createFields
})

function rowActions(row: Row): string[] {
  const value = row.available_actions
  return Array.isArray(value) ? (value as string[]).filter((action): action is string => typeof action === 'string') : []
}

function warnings(row: Row): string[] {
  const value = row.warnings
  return Array.isArray(value) ? (value as string[]).filter((warning): warning is string => typeof warning === 'string') : []
}

function displayValue(row: Row, field: string): string {
  const value = row[field]
  if (Array.isArray(value) || (value !== null && typeof value === 'object')) return '—'
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

function formatPressure(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  return Number.isFinite(number) ? `${number}MPa` : String(value)
}

function fieldPrompt(field: string): string {
  if (field === '口径规格') return '如 DN100 / 150mm'
  if (field === '出水压力') return '单位 MPa，正常范围 0.10～0.80'
  return `请输入${field}`
}

function resetFilters() {
  filters.value = { 消防栓编号: '', 口径规格: '', 所在道路: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  formMode.value = 'create'
  formTarget.value = null
  formError.value = ''
  formValues.value = Object.fromEntries(createFields.map((field) => [field, '']))
  formVisible.value = true
}

function closeForm() {
  formVisible.value = false
  formTarget.value = null
}

function openCompleteForm(row: Row) {
  formMode.value = 'complete'
  formTarget.value = row
  formError.value = ''
  formValues.value = Object.fromEntries(
    completeFields.map((field) => [field, typeof row[field] === 'string' ? row[field] as string : '']),
  )
  formVisible.value = true
}

function openTestForm(row: Row) {
  formMode.value = 'test'
  formTarget.value = row
  formError.value = ''
  formValues.value = {
    出水压力: '',
    上次试水日: typeof row['上次试水日'] === 'string' ? row['上次试水日'] as string : '',
    维护单位: typeof row['维护单位'] === 'string' ? row['维护单位'] as string : '',
  }
  formVisible.value = true
}

async function submitForm() {
  if (formMode.value === 'create') {
    const values = Object.fromEntries(Object.entries(formValues.value).filter(([, value]) => value.trim()))
    await submitRequest('', { values }, '消防栓已登记')
    return
  }

  const target = formTarget.value
  if (!target) return
  const id = String(target.id)
  const values = Object.fromEntries(Object.entries(formValues.value).filter(([, value]) => value.trim()))
  const action = formMode.value === 'complete' ? '补全档案' : '试水检测'
  await submitRequest(`/${id}/actions`, { action, ...values }, `消防栓已${action}`)
}

async function submitRequest(path: string, body: Record<string, unknown>, successMessage: string): Promise<boolean> {
  formError.value = ''
  try {
    const response = await request(`${ENDPOINT}${path}`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
    const payload = await response.json().catch(() => null) as { ok?: boolean, message?: string } | null
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message || '消防栓操作未生效，请稍后重试')
    }
    errorMessage.value = successMessage
    const targetId = formTarget.value?.id
    closeForm()
    await reload()
    if (targetId && detail.value?.id === targetId) await loadDetail(Number(targetId))
    return true
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '消防栓操作失败'
    return false
  }
}

async function openDetail(row: Row) {
  await loadDetail(Number(row.id))
}

async function loadDetail(id: number) {
  errorMessage.value = ''
  try {
    const [entryResponse, recordsResponse] = await Promise.all([
      request(`${ENDPOINT}/${id}`),
      request(`${ENDPOINT}/${id}/maintenance-records`),
    ])
    if (!entryResponse.ok) throw new Error('消防栓详情读取失败')
    if (!recordsResponse.ok) throw new Error('消防栓维护记录读取失败')
    detail.value = (await entryResponse.json()) as Row
    const recordsPayload = await recordsResponse.json() as { items?: MaintenanceRecord[] }
    maintenanceRecords.value = recordsPayload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '消防栓详情读取失败'
  }
}

async function runAction(action: string, row: Row) {
  if (action === '补全档案') {
    openCompleteForm(row)
    return
  }
  if (action === '试水检测') {
    openTestForm(row)
    return
  }

  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json().catch(() => null) as { ok?: boolean, message?: string } | null
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message || '消防栓动作未生效，请稍后重试')
    }
    errorMessage.value = payload?.message || `消防栓已${action}`
    await reload()
    if (detail.value?.id === row.id) await loadDetail(Number(row.id))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '消防栓操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const activeFilters = Object.fromEntries(
    Object.entries(filters.value).filter(([, value]) => value.trim()),
  )
  const query = new URLSearchParams(activeFilters).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('消防栓列表读取失败')
    }
    const payload = await response.json() as { items?: Row[], total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (detail.value) {
      const refreshed = rows.value.find((row) => row.id === detail.value?.id)
      if (refreshed) detail.value = refreshed
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '消防栓列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.page-actions { display: flex; gap: 8px; }
.inline-warnings { margin: 4px 0 0; padding-left: 16px; color: #b45309; font-size: 12px; }
.muted-text { color: var(--muted); font-size: 12px; }
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgb(15 23 42 / 45%);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  z-index: 20;
}
.modal {
  width: min(520px, 100%);
  max-height: 90vh;
  overflow: auto;
  background: #fff;
  border-radius: 10px;
  padding: 18px;
}
.detail-modal { width: min(960px, 100%); }
.modal h3, .modal h4 { margin: 0 0 14px; }
.form-item { display: block; margin-bottom: 10px; }
.form-item span, .detail-grid dt { color: var(--muted); font-size: 12px; }
.form-item input { width: 100%; margin-top: 4px; padding: 7px 8px; border: 1px solid var(--border); border-radius: 6px; }
.modal-actions, .detail-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
.detail-head { display: flex; justify-content: space-between; align-items: center; }
.detail-grid { display: grid; grid-template-columns: 110px 1fr 110px 1fr; gap: 8px 12px; margin: 0 0 12px; }
.detail-grid dt { color: var(--muted); }
.detail-grid dd { margin: 0; font-size: 13px; }
.tag { display: inline-block; margin-left: 6px; padding: 1px 6px; border-radius: 999px; background: #e0e7ff; color: #3730a3; font-size: 12px; }
.tag.warning { background: #fef3c7; color: #92400e; }
.warning-list { margin: 0 0 12px; padding-left: 18px; color: #b45309; font-size: 13px; }
.record-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.record-table th, .record-table td { border: 1px solid var(--border); padding: 6px 8px; text-align: left; }
</style>
