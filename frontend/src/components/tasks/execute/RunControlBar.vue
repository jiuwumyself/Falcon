<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Play, Square, ExternalLink, Loader, History } from 'lucide-vue-next'
import type { RunStatus, TaskRun } from '@/types/task'

const props = defineProps<{
  selectedRun: TaskRun | null
  runs: TaskRun[]
  durationSeconds: number     // task.duration_seconds，用于进度条满刻度
  busy: boolean                // 父组件正在 RPC 中（开始/取消处理中）
  isDark: boolean
}>()

const emit = defineEmits<{
  (e: 'start'): void          // 父组件接收后弹 modal 选机器
  (e: 'stop'): void
  (e: 'view-report'): void
  (e: 'select', runId: string): void
}>()

const ACTIVE: RunStatus[] = ['pre_checking', 'pending', 'running', 'cancelling']
const TERMINAL: RunStatus[] = ['pre_check_failed', 'success', 'failed', 'timeout', 'cancelled']

const isActive = computed(() => !!props.selectedRun && ACTIVE.includes(props.selectedRun.status))
const isTerminal = computed(() => !!props.selectedRun && TERMINAL.includes(props.selectedRun.status))
const canViewReport = computed(() =>
  isTerminal.value && props.selectedRun?.status === 'success',
)

// ─── 计时器 + 进度条 ───
const now = ref(Date.now())
let tickTimer: number | undefined

onMounted(() => {
  tickTimer = window.setInterval(() => { now.value = Date.now() }, 1000)
})
onBeforeUnmount(() => {
  if (tickTimer) clearInterval(tickTimer)
})

const elapsedSec = computed<number>(() => {
  const r = props.selectedRun
  if (!r?.started_at) return 0
  const start = new Date(r.started_at).getTime()
  const end = r.finished_at ? new Date(r.finished_at).getTime() : now.value
  return Math.max(0, Math.floor((end - start) / 1000))
})

function fmtTime(s: number): string {
  const m = Math.floor(s / 60), sec = s % 60
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}
const elapsedStr = computed(() => fmtTime(elapsedSec.value))
const totalStr = computed(() => fmtTime(props.durationSeconds || 0))

const progressPct = computed(() => {
  if (!props.durationSeconds) return 0
  return Math.min(100, (elapsedSec.value / props.durationSeconds) * 100)
})

// ─── 状态徽章 ───
const STATUS_META: Record<RunStatus, { label: string; color: string }> = {
  pre_checking: { label: '预检中', color: '#9ca3af' },
  pre_check_failed: { label: '预检失败', color: '#ef4444' },
  pending: { label: '排队中', color: '#9ca3af' },
  running: { label: '执行中', color: '#3b82f6' },
  cancelling: { label: '取消中', color: '#f59e0b' },
  success: { label: '成功', color: '#10b981' },
  failed: { label: '失败', color: '#ef4444' },
  timeout: { label: '超时', color: '#f59e0b' },
  cancelled: { label: '已取消', color: '#9ca3af' },
}
const statusInfo = computed(() => {
  if (!props.selectedRun) return { label: '待启动', color: '#9ca3af' }
  return STATUS_META[props.selectedRun.status] || { label: props.selectedRun.status, color: '#6b7280' }
})

// ─── 历史 ribbon ───
const SHORT_RUN_LIMIT = 8
const ribbonRuns = computed(() => props.runs.slice(0, SHORT_RUN_LIMIT))

function selectRun(rid: string) {
  emit('select', rid)
}

function fmtRunTitle(r: TaskRun): string {
  if (r.started_at) {
    const d = new Date(r.started_at)
    return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
  }
  return r.run_id.slice(0, 6)
}
</script>

<template>
  <div
    class="flex items-center gap-3 px-3 py-2 rounded-xl"
    :style="{
      background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)',
      border: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
    }"
  >
    <!-- 状态徽章 -->
    <span
      class="flex items-center gap-1.5 px-2 py-1 rounded text-[11px] flex-shrink-0"
      :style="{
        background: `${statusInfo.color}1f`,
        color: statusInfo.color,
      }"
    >
      <span class="w-1.5 h-1.5 rounded-full"
            :style="{ background: statusInfo.color }" />
      {{ statusInfo.label }}
    </span>

    <!-- 计时器 + 进度条 -->
    <div class="flex items-center gap-2 flex-1 min-w-0 max-w-[400px]">
      <span class="text-[11px] tabular-nums flex-shrink-0"
            :style="{ color: isDark ? 'rgba(255,255,255,0.65)' : 'rgba(0,0,0,0.65)' }">
        {{ elapsedStr }}
        <span :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.4)' }">
          / {{ totalStr }}
        </span>
      </span>
      <div class="flex-1 h-1 rounded-full overflow-hidden"
           :style="{ background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' }">
        <div class="h-full rounded-full transition-all duration-300"
             :style="{
               width: `${progressPct}%`,
               background: isActive ? '#3b82f6' : statusInfo.color,
             }" />
      </div>
    </div>

    <!-- 按钮组 -->
    <div class="flex items-center gap-1.5 flex-shrink-0">
      <!-- 二态按钮：开始 ⇄ 停止 -->
      <button
        v-if="!isActive"
        class="flex items-center gap-1 px-3 py-1.5 rounded-lg text-[12px] cursor-pointer disabled:opacity-50"
        :style="{ background: '#10b981', color: '#fff' }"
        :disabled="busy"
        @click="emit('start')"
      >
        <Loader v-if="busy" :size="12" class="animate-spin" />
        <Play v-else :size="12" />
        {{ selectedRun ? '重新开始' : '开始' }}
      </button>
      <button
        v-else
        class="flex items-center gap-1 px-3 py-1.5 rounded-lg text-[12px] cursor-pointer disabled:opacity-50"
        :style="{ background: '#ef4444', color: '#fff' }"
        :disabled="busy"
        @click="emit('stop')"
      >
        <Loader v-if="busy" :size="12" class="animate-spin" />
        <Square v-else :size="12" />
        停止
      </button>

      <!-- 报告按钮（仅 success 终态可点）-->
      <button
        v-if="canViewReport"
        class="flex items-center gap-1 px-2 py-1.5 rounded-lg text-[12px] cursor-pointer"
        :style="{
          background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)',
          color: isDark ? 'rgba(255,255,255,0.75)' : 'rgba(0,0,0,0.7)',
        }"
        @click="emit('view-report')"
      >
        <ExternalLink :size="11" />
        查看报告
      </button>
    </div>

    <!-- 分隔 -->
    <div v-if="ribbonRuns.length"
         class="w-px h-6 flex-shrink-0"
         :style="{ background: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)' }" />

    <!-- 历史 run ribbon -->
    <div v-if="ribbonRuns.length"
         class="flex items-center gap-1 overflow-x-auto flex-shrink min-w-0">
      <History :size="11" class="flex-shrink-0"
               :color="isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)'" />
      <button
        v-for="r in ribbonRuns"
        :key="r.run_id"
        class="px-1.5 py-0.5 rounded text-[10px] cursor-pointer flex-shrink-0"
        :title="`${r.run_id} · ${r.status}`"
        :style="{
          background: r.run_id === selectedRun?.run_id
            ? (isDark ? 'rgba(59,130,246,0.18)' : 'rgba(59,130,246,0.12)')
            : 'transparent',
          color: r.run_id === selectedRun?.run_id
            ? (isDark ? '#93c5fd' : '#2563eb')
            : (STATUS_META[r.status]?.color || '#6b7280'),
        }"
        @click="selectRun(r.run_id)"
      >
        {{ fmtRunTitle(r) }}
      </button>
    </div>
  </div>
</template>
