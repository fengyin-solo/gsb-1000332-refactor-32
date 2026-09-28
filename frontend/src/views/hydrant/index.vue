<template>
  <section class="page" data-module="hydrant">
    <header class="page-head">
      <div>
        <h2>消防栓管理管理</h2>
        <p class="page-desc">维护消防栓，围绕消防栓编号、口径规格、所在道路、出水压力做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记消防栓</button>
        <button class="btn" type="button" @click="toggleLogs">
          {{ showLogs ? '返回消防栓列表' : '查看维护记录' }}
        </button>
        <button class="btn" type="button" @click="exportRows">导出消防栓管理清单</button>
      </div>
    </header>

    <div v-if="!showLogs" class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="!showLogs" class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table v-if="!showLogs" class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ displayCell(row, column) }}</td>
          <td class="row-actions">
            <template v-if="visibleActions(row).length">
              <button
                v-for="action in visibleActions(row)"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
            <span v-else class="muted-text">无可执行动作</span>
            <ul v-if="row.warnings && row.warnings.length" class="warn-list">
              <li v-for="warn in row.warnings" :key="warn">{{ warn }}</li>
            </ul>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无消防栓管理数据，可先登记消防栓</td>
        </tr>
      </tbody>
    </table>

    <table v-else class="data-table">
      <thead>
        <tr>
          <th v-for="column in logColumns" :key="column">{{ column }}</th>
          <th>当前可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="log in logs" :key="String(log.id)">
          <td>{{ log['消防栓编号'] ?? '—' }}</td>
          <td>{{ log.action }}</td>
          <td>{{ log.detail }}</td>
          <td>{{ log.operated_at }}</td>
          <td>{{ log.current_status }}</td>
          <td class="row-actions">
            <template v-if="log.available_actions && log.available_actions.length">
              <span v-for="action in log.available_actions" :key="action" class="log-action">{{ action }}</span>
            </template>
            <span v-else class="muted-text">无可执行动作</span>
            <ul v-if="log.warnings && log.warnings.length" class="warn-list">
              <li v-for="warn in log.warnings" :key="warn">{{ warn }}</li>
            </ul>
          </td>
        </tr>
        <tr v-if="!logs.length">
          <td :colspan="logColumns.length + 1" class="empty-state">暂无消防栓维护记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span v-if="!showLogs">共 {{ total }} 条消防栓管理记录</span>
      <span v-else>共 {{ logs.length }} 条维护记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type HydrantRow = Row & {
  status?: string
  available_actions?: string[]
  blocked_actions?: Record<string, string>
  warnings?: string[]
}
type MaintenanceLog = {
  id: number
  action: string
  detail: string
  operated_at: string
  current_status: string
  available_actions: string[]
  warnings: string[]
  '消防栓编号'?: string
}

const ENDPOINT = '/api/hydrant'
const columns = ["消防栓编号", "口径规格", "所在道路", "出水压力", "上次试水日", "维护单位", "完好情况", "设施状态"]
const logColumns = ["消防栓编号", "动作", "记录说明", "操作时间", "当前状态"]
const fallbackActions = ["试水检测", "安排维修", "登记拆除"]
const stats = [{"label": "完好消火栓", "value": 0}, {"label": "锈蚀消火栓", "value": 0}, {"label": "无水消火栓", "value": 0}]

const rows = ref<HydrantRow[]>([])
const logs = ref<MaintenanceLog[]>([])
const showLogs = ref(false)
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function displayCell(row: HydrantRow, column: string): string | number | null {
  // 「设施状态」统一展示服务端归一后的生命周期状态，避免两套状态不一致。
  if (column === '设施状态' && row.status) {
    return row.status
  }
  return row[column] ?? '—'
}

function visibleActions(row: HydrantRow): string[] {
  // 按钮可见性唯一来源是后端统一判定；旧接口缺字段时退回全部动作保持兼容。
  return row.available_actions ?? fallbackActions
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function toggleLogs() {
  showLogs.value = !showLogs.value
  errorMessage.value = ''
  if (showLogs.value) {
    void loadLogs()
  } else {
    void reload()
  }
}

async function loadLogs() {
  try {
    const response = await request(`${ENDPOINT}/maintenance`)
    if (!response.ok) {
      throw new Error('维护记录读取失败')
    }
    const payload = await response.json()
    logs.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '维护记录读取失败'
  }
}

function openCreate() {
  errorMessage.value = '消防栓登记入口尚未接入审批流'
}

async function runAction(action: string, row: HydrantRow) {
  errorMessage.value = ''
  try {
    // 试水检测需要本次出水压力；没有历史压力时必须填写。
    let pressure: string | null = null
    if (action === '试水检测') {
      const input = window.prompt(`请输入消防栓 ${String(row['消防栓编号'] ?? '')} 本次出水压力（MPa，合理区间 0.10~0.70）`, '')
      if (input === null) {
        return
      }
      pressure = input.trim()
    }
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, pressure } }),
    })
    if (!response.ok) {
      throw new Error('消防栓管理动作未生效，请稍后重试')
    }
    const payload = (await response.json()) as { ok: boolean; message: string }
    errorMessage.value = payload.message || (payload.ok ? '操作已生效' : '动作未生效')
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '消防栓管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('消防栓列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '消防栓管理列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.warn-list {
  margin: 4px 0 0;
  padding-left: 16px;
  color: #b45309;
  font-size: 12px;
  line-height: 1.5;
}

.muted-text {
  color: #94a3b8;
  font-size: 12px;
}

.log-action {
  margin-right: 8px;
  color: #0f766e;
  font-size: 12px;
}
</style>
