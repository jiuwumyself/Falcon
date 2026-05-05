<script setup lang="ts">
import { computed, watch } from 'vue'
import { Plus, Trash2 } from 'lucide-vue-next'
import type { TGKind, ThreadGroupConfig, UltimatePeakRow } from '@/types/task'
import { MAX_DURATION_SECONDS, MAX_USERS } from '../configStageCtx'

const props = defineProps<{
  config: ThreadGroupConfig
  isDark: boolean
}>()

const emit = defineEmits<{
  (e: 'update:config', next: ThreadGroupConfig): void
}>()

const isUltimate = computed(() => props.config.kind === 'UltimateThreadGroup')

// ── Ultimate 多峰行 ──────────────────────────────────────────────────

const defaultPeakRow = (): UltimatePeakRow => ({
  users: 500, initial_delay: 0, ramp_up: 5, hold: 60, shutdown: 5,
})

// 兼容老格式（flat dict）→ rows 数组
const ultimateRows = computed<UltimatePeakRow[]>(() => {
  const p = props.config.params
  if (Array.isArray(p.rows)) return p.rows as UltimatePeakRow[]
  if ('users' in p) {
    return [{ users: Number(p.users), initial_delay: Number(p.initial_delay ?? 0),
              ramp_up: Number(p.ramp_up), hold: Number(p.hold), shutdown: Number(p.shutdown) }]
  }
  return [defaultPeakRow()]
})

function emitRows(rows: UltimatePeakRow[]) {
  emit('update:config', { ...props.config, params: { rows } })
}

function updateRow(idx: number, field: keyof UltimatePeakRow, rawVal: string) {
  const val = Math.max(0, Number(rawVal) || 0)
  const next = ultimateRows.value.map((r, i) => i === idx ? { ...r, [field]: val } : r)
  emitRows(next)
}

function addRow() {
  const last = ultimateRows.value.at(-1)
  const newDelay = last ? last.initial_delay + last.ramp_up + last.hold + last.shutdown + 10 : 0
  emitRows([...ultimateRows.value, { ...defaultPeakRow(), initial_delay: newDelay }])
}

function removeRow(idx: number) {
  if (ultimateRows.value.length <= 1) return
  emitRows(ultimateRows.value.filter((_, i) => i !== idx))
}

const ultimateColDefs: { key: keyof UltimatePeakRow; label: string; max: number }[] = [
  { key: 'users',         label: '用户数',    max: MAX_USERS },
  { key: 'initial_delay', label: '延迟(s)',   max: MAX_DURATION_SECONDS },
  { key: 'ramp_up',       label: '上升(s)',   max: MAX_DURATION_SECONDS },
  { key: 'hold',          label: '保持(s)',   max: MAX_DURATION_SECONDS },
  { key: 'shutdown',      label: '下降(s)',   max: MAX_DURATION_SECONDS },
]

// ── 其他场景 ────────────────────────────────────────────────────────

function defaultsFor(kind: TGKind): Record<string, number | string> {
  if (kind === 'ThreadGroup') return { users: 10, ramp_up: 5, duration: 60 }
  if (kind === 'SteppingThreadGroup') {
    return { initial_threads: 0, step_users: 10, step_delay: 30,
             step_count: 10, hold: 60, shutdown: 5 }
  }
  if (kind === 'ConcurrencyThreadGroup') {
    return { target_concurrency: 100, ramp_up: 10, steps: 5, hold: 60, unit: 'S' }
  }
  return { target_rps: 500, ramp_up: 60, steps: 10, hold: 600, unit: 'M' }
}

function setParam(name: string, value: number | string) {
  emit('update:config', {
    ...props.config,
    params: { ...props.config.params, [name]: value },
  })
}

// Fill missing defaults after config changes (e.g. scenario switch)
watch(
  () => [props.config.kind, Object.keys(props.config.params).length] as const,
  () => {
    if (props.config.kind === 'UltimateThreadGroup') {
      const p = props.config.params
      // 老格式迁移：有 users 但没 rows → 包成 rows
      if ('users' in p && !Array.isArray(p.rows)) {
        emitRows([{ users: Number(p.users), initial_delay: Number(p.initial_delay ?? 0),
                    ramp_up: Number(p.ramp_up), hold: Number(p.hold), shutdown: Number(p.shutdown) }])
      } else if (!Array.isArray(p.rows)) {
        emitRows([defaultPeakRow()])
      }
      return
    }
    const d = defaultsFor(props.config.kind)
    const p = props.config.params
    let changed = false
    const next = { ...p }
    for (const k of Object.keys(d)) {
      if (!(k in next)) { next[k] = d[k]; changed = true }
    }
    if (changed) emit('update:config', { ...props.config, params: next })
  },
  { immediate: true },
)

const inputStyle = computed(() => ({
  background: props.isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
  border: `1px solid ${props.isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
  color: props.isDark ? '#fff' : '#1a1a2e',
}))

interface Field {
  name: string
  label: string
  max: number
  hint?: string
}

// 按 kind 返回要展示的字段清单。ArrivalsThreadGroup 和 ConcurrencyThreadGroup
// 结构相似但第一字段含义不同（RPS vs 并发），label 区分开。
const fields = computed<Field[]>(() => {
  const k = props.config.kind
  if (k === 'ThreadGroup') return [
    { name: 'users', label: '虚拟用户数', max: MAX_USERS },
    { name: 'ramp_up', label: 'Ramp-up (秒)', max: MAX_DURATION_SECONDS },
    { name: 'duration', label: '持续时间 (秒)', max: MAX_DURATION_SECONDS },
  ]
  if (k === 'SteppingThreadGroup') return [
    { name: 'initial_threads', label: '初始用户', max: MAX_USERS },
    { name: 'step_users', label: '每步加用户', max: MAX_USERS },
    { name: 'step_count', label: '步数', max: 1000 },
    { name: 'step_delay', label: '每步间隔 (秒)', max: MAX_DURATION_SECONDS },
    { name: 'hold', label: '保持时长 (秒)', max: MAX_DURATION_SECONDS },
    { name: 'shutdown', label: '退出间隔 (秒)', max: MAX_DURATION_SECONDS },
  ]
  if (k === 'ConcurrencyThreadGroup') return [
    { name: 'target_concurrency', label: '目标并发', max: MAX_USERS },
    { name: 'ramp_up', label: 'Ramp-up (秒)', max: MAX_DURATION_SECONDS },
    { name: 'steps', label: '阶梯数', max: 1000 },
    { name: 'hold', label: '保持时长', max: MAX_DURATION_SECONDS, hint: '单位跟随 Unit' },
  ]
  if (k === 'UltimateThreadGroup') return [
    { name: 'users', label: '峰值用户数', max: MAX_USERS },
    { name: 'initial_delay', label: '初始延迟 (秒)', max: MAX_DURATION_SECONDS },
    { name: 'ramp_up', label: '上升时长 (秒)', max: MAX_DURATION_SECONDS },
    { name: 'hold', label: '保持时长 (秒)', max: MAX_DURATION_SECONDS },
    { name: 'shutdown', label: '下降时长 (秒)', max: MAX_DURATION_SECONDS },
  ]
  // ArrivalsThreadGroup
  return [
    { name: 'target_rps', label: '目标 RPS', max: 1_000_000 },
    { name: 'ramp_up', label: 'Ramp-up (秒)', max: MAX_DURATION_SECONDS },
    { name: 'steps', label: '阶梯数', max: 1000 },
    { name: 'hold', label: '保持时长', max: MAX_DURATION_SECONDS, hint: '单位跟随 Unit' },
  ]
})

const hasUnit = computed(() =>
  props.config.kind === 'ConcurrencyThreadGroup' ||
  props.config.kind === 'ArrivalsThreadGroup',
)
</script>

<template>
  <div class="flex flex-col gap-3">
    <p
      class="text-[10px] uppercase tracking-[0.2em]"
      :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }"
    >参数</p>

    <!-- Ultimate ThreadGroup：多峰行编辑器 -->
    <template v-if="isUltimate">
      <!-- 列标题 -->
      <div class="grid gap-1 items-end" style="grid-template-columns: repeat(5, 1fr) 28px">
        <span
          v-for="col in ultimateColDefs" :key="col.key"
          class="text-[9px] uppercase tracking-wider text-center truncate pb-0.5"
          :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
        >{{ col.label }}</span>
        <span />
      </div>

      <!-- 每个波峰行 -->
      <div
        v-for="(row, idx) in ultimateRows" :key="idx"
        class="grid gap-1 items-center"
        style="grid-template-columns: repeat(5, 1fr) 28px"
      >
        <input
          v-for="col in ultimateColDefs" :key="col.key"
          :value="row[col.key]"
          type="number"
          min="0"
          :max="col.max"
          class="w-full px-1.5 py-1.5 rounded-md text-[12px] font-mono outline-none text-center"
          :style="inputStyle"
          @input="updateRow(idx, col.key, ($event.target as HTMLInputElement).value)"
        />
        <button
          class="flex items-center justify-center rounded-md h-[30px] w-[28px] transition-opacity"
          :class="ultimateRows.length <= 1 ? 'opacity-20 cursor-not-allowed' : 'opacity-60 hover:opacity-100 cursor-pointer'"
          :style="{ color: '#ef4444' }"
          :disabled="ultimateRows.length <= 1"
          @click="removeRow(idx)"
        >
          <Trash2 :size="12" />
        </button>
      </div>

      <!-- 添加波峰按钮 -->
      <button
        class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[11px] cursor-pointer transition-opacity hover:opacity-80 self-start"
        :style="{
          background: isDark ? 'rgba(239,68,68,0.1)' : 'rgba(239,68,68,0.07)',
          color: '#ef4444',
          border: `1px solid ${isDark ? 'rgba(239,68,68,0.25)' : 'rgba(239,68,68,0.2)'}`,
        }"
        @click="addRow"
      >
        <Plus :size="11" />
        添加波峰
      </button>
    </template>

    <!-- 其他场景：原有网格布局 -->
    <template v-else>
      <div class="grid grid-cols-2 gap-3">
        <div v-for="f in fields" :key="f.name">
          <label
            class="block text-[10px] uppercase tracking-wider mb-1 truncate"
            :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }"
            :title="f.hint || ''"
          >{{ f.label }}</label>
          <input
            :value="config.params[f.name]"
            type="number"
            :min="0"
            :max="f.max"
            class="w-full px-2.5 py-1.5 rounded-md text-[13px] font-mono outline-none"
            :style="inputStyle"
            @input="setParam(f.name, Number(($event.target as HTMLInputElement).value))"
          />
        </div>
        <div v-if="hasUnit">
          <label
            class="block text-[10px] uppercase tracking-wider mb-1"
            :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }"
          >Unit</label>
          <select
            :value="config.params.unit"
            class="w-full px-2.5 py-1.5 rounded-md text-[13px] outline-none"
            :style="inputStyle"
            @change="setParam('unit', ($event.target as HTMLSelectElement).value)"
          >
            <option value="S">秒 (S)</option>
            <option value="M">分 (M)</option>
          </select>
        </div>
      </div>
    </template>
  </div>
</template>
