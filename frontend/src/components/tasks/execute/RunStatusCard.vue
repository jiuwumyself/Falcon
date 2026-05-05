<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Play, Square, RotateCcw, FileText, AlertCircle, Loader, Clock, CheckCircle, XCircle } from 'lucide-vue-next'
import type { TaskRun, RunStatus } from '@/types/task'

const props = defineProps<{
  run: TaskRun | null
  isDark: boolean
  busy: boolean
}>()

const emit = defineEmits<{
  (e: 'start'): void
  (e: 'cancel'): void
  (e: 'view-report'): void
}>()

const TERMINAL: RunStatus[] = ['pre_check_failed', 'success', 'failed', 'timeout', 'cancelled']

const statusMeta = computed(() => {
  const s = props.run?.status
  switch (s) {
    case 'pre_checking':
      return { label: '环境检测中…', color: '#94a3b8', icon: Loader }
    case 'pre_check_failed':
      return { label: '环境检测失败', color: '#ef4444', icon: AlertCircle }
    case 'pending':
      return { label: '排队中', color: '#f59e0b', icon: Clock }
    case 'running':
      return { label: '运行中', color: '#10b981', icon: Loader }
    case 'cancelling':
      return { label: '正在停止…', color: '#f59e0b', icon: Loader }
    case 'success':
      return { label: '执行成功', color: '#3b82f6', icon: CheckCircle }
    case 'failed':
      return { label: '执行失败', color: '#ef4444', icon: XCircle }
    case 'timeout':
      return { label: '执行超时', color: '#ef4444', icon: AlertCircle }
    case 'cancelled':
      return { label: '已取消', color: '#94a3b8', icon: XCircle }
    default:
      return { label: '尚未运行', color: '#94a3b8', icon: Play }
  }
})

const isTerminal = computed(() => !!props.run && TERMINAL.includes(props.run.status))
const canCancel = computed(() =>
  !!props.run && ['pre_checking', 'pending', 'running'].includes(props.run.status),
)
const canViewReport = computed(() =>
  !!props.run && ['success', 'cancelled', 'timeout', 'failed'].includes(props.run.status),
)
const isSpinning = computed(() =>
  !!props.run && ['pre_checking', 'running', 'cancelling'].includes(props.run.status),
)

// 实时秒数计时（运行中）
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  timer = setInterval(() => { now.value = Date.now() }, 1000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})

const elapsedSec = computed(() => {
  if (!props.run?.started_at) return 0
  const start = new Date(props.run.started_at).getTime()
  const end = props.run.finished_at ? new Date(props.run.finished_at).getTime() : now.value
  return Math.max(0, Math.floor((end - start) / 1000))
})

const totalSec = computed(() => {
  if (!props.run) return 0
  return (props.run.ramp_up_seconds || 0) + (props.run.duration_seconds || 0)
})

function formatDuration(sec: number): string {
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  if (m < 60) return `${m}:${String(s).padStart(2, '0')}`
  const h = Math.floor(m / 60)
  return `${h}:${String(m % 60).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

const progressPct = computed(() => {
  if (!totalSec.value) return 0
  return Math.min(100, Math.floor(elapsedSec.value / totalSec.value * 100))
})

const showProgress = computed(() => props.run?.status === 'running' && totalSec.value > 0)

// 终态总请求数（横向 inline）
const totalRequests = computed(() => {
  if (!props.run || !isTerminal.value) return null
  return props.run.total_requests || 0
})

const showError = computed(() =>
  !!props.run?.error_message &&
  (props.run.status === 'failed' || props.run.status === 'timeout' || props.run.status === 'pre_check_failed'),
)
</script>

<template>
  <div class="space-y-2">
    <!-- 横长条主体 -->
    <div
      class="rounded-2xl px-4 py-3 flex items-center gap-3"
      :style="{
        background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(255,255,255,0.7)',
        border: isDark ? '1px solid rgba(255,255,255,0.08)' : '1px solid rgba(0,0,0,0.06)',
        backdropFilter: 'blur(40px)',
      }"
    >
      <!-- 1. 状态 icon -->
      <div
        class="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
        :style="{ background: `${statusMeta.color}1a` }"
      >
        <component
          :is="statusMeta.icon"
          :size="20"
          :color="statusMeta.color"
          :class="{ 'animate-spin': isSpinning }"
        />
      </div>

      <!-- 2. 状态文本 + run_id + 计时 + 总请求数（一行内） -->
      <div class="flex-1 min-w-0 flex items-baseline flex-wrap gap-x-2 gap-y-0.5">
        <span class="text-[14px] font-semibold whitespace-nowrap" :style="{ color: statusMeta.color }">
          {{ statusMeta.label }}
        </span>
        <span
          v-if="run?.run_id"
          class="text-[12px] font-mono whitespace-nowrap"
          :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.5)' }"
        >· {{ run.run_id }}</span>
        <span
          v-if="elapsedSec > 0"
          class="text-[12px] tabular-nums whitespace-nowrap"
          :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.5)' }"
        >· {{ formatDuration(elapsedSec) }}<template v-if="totalSec > 0 && !isTerminal"> / {{ formatDuration(totalSec) }}</template></span>
        <span
          v-if="totalRequests !== null && totalRequests > 0"
          class="text-[12px] tabular-nums whitespace-nowrap"
          :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.5)' }"
        >· 总请求 {{ totalRequests.toLocaleString() }}</span>
        <span
          v-if="!run"
          class="text-[12px] whitespace-nowrap"
          :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }"
        >点击右侧按钮开始压测</span>
      </div>

      <!-- 3. 进度条（运行中） -->
      <div
        v-if="showProgress"
        class="flex items-center gap-2 flex-shrink-0"
        :style="{ minWidth: '160px' }"
      >
        <div
          class="flex-1 h-1.5 rounded-full overflow-hidden"
          :style="{ background: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)' }"
        >
          <div
            class="h-full transition-all duration-500"
            :style="{
              width: `${progressPct}%`,
              background: 'linear-gradient(90deg, #10b981, #34d399)',
            }"
          />
        </div>
        <span
          class="text-[11px] tabular-nums w-9 text-right"
          :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.5)' }"
        >{{ progressPct }}%</span>
      </div>

      <!-- 4. 操作按钮组（最右） -->
      <div class="flex items-center gap-2 flex-shrink-0">
        <button
          v-if="!run || isTerminal"
          type="button"
          :disabled="busy"
          class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-[13px] font-medium transition-all"
          :class="{ 'opacity-50 cursor-not-allowed': busy }"
          :style="{
            background: 'linear-gradient(135deg, #10b981, #059669)',
            color: '#fff',
          }"
          @click="emit('start')"
        >
          <component :is="run ? RotateCcw : Play" :size="14" />
          {{ run ? '重新运行' : '开始压测' }}
        </button>
        <button
          v-if="canCancel"
          type="button"
          :disabled="busy || run?.status === 'cancelling'"
          class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-[13px] font-medium transition-all"
          :class="{ 'opacity-50 cursor-not-allowed': busy || run?.status === 'cancelling' }"
          :style="{
            background: 'rgba(239,68,68,0.12)',
            border: '1px solid rgba(239,68,68,0.3)',
            color: '#ef4444',
          }"
          @click="emit('cancel')"
        >
          <Square :size="13" />
          {{ run?.status === 'cancelling' ? '正在停止' : '取消' }}
        </button>
        <button
          v-if="canViewReport"
          type="button"
          class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-[13px] font-medium transition-all"
          :style="{
            background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)',
            color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.7)',
          }"
          @click="emit('view-report')"
        >
          <FileText :size="13" />
          JMeter 报告
        </button>
      </div>
    </div>

    <!-- 错误信息（失败时单独一行展开） -->
    <div
      v-if="showError"
      class="rounded-lg px-3 py-2 text-[12px]"
      :style="{
        background: 'rgba(239,68,68,0.08)',
        border: '1px solid rgba(239,68,68,0.2)',
        color: '#ef4444',
      }"
    >
      <div class="font-semibold mb-1">错误信息</div>
      <div class="font-mono whitespace-pre-wrap break-words">{{ run?.error_message }}</div>
    </div>
  </div>
</template>
