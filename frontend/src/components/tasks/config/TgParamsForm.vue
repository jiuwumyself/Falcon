<script setup lang="ts">
import { computed, watch } from 'vue'
import type { TGKind, ThreadGroupConfig } from '@/types/task'
import { MAX_DURATION_SECONDS, MAX_USERS } from '../configStageCtx'

const props = defineProps<{
  config: ThreadGroupConfig
  isDark: boolean
}>()

const emit = defineEmits<{
  (e: 'update:config', next: ThreadGroupConfig): void
}>()

function defaultsFor(kind: TGKind): Record<string, number | string> {
  if (kind === 'ThreadGroup') return { users: 10, ramp_up: 5, duration: 60 }
  if (kind === 'SteppingThreadGroup') {
    return { initial_threads: 0, step_users: 10, step_delay: 30,
             step_count: 10, hold: 60, shutdown: 5 }
  }
  if (kind === 'ConcurrencyThreadGroup') {
    return { target_concurrency: 100, ramp_up: 10, steps: 5, hold: 60, unit: 'S' }
  }
  if (kind === 'UltimateThreadGroup') {
    return { users: 500, initial_delay: 0, ramp_up: 5, hold: 60, shutdown: 5 }
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
  </div>
</template>
