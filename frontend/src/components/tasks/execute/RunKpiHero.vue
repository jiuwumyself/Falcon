<script setup lang="ts">
import { computed } from 'vue'
import { Motion } from 'motion-v'
import type { RunMetrics, Task, TaskRun } from '@/types/task'
import {
  hasOnlyArrivals, lastValue, plannedThreads, targetRps,
} from '@/lib/planSummary'

const props = defineProps<{
  task: Task
  run: TaskRun | null
  metrics: RunMetrics | null
  isDark: boolean
}>()

// 三态判定：决定主色和动效。
// - idle  ：还没运行 / 没选中任何 run → 主色淡，水印浮着
// - active：pre_checking / pending / running / cancelling → 主色实色 + 实时刷新
// - terminal：success / failed / timeout / cancelled / pre_check_failed → 终值定格
const ACTIVE = ['pre_checking', 'pending', 'running', 'cancelling'] as const
const TERMINAL = ['success', 'failed', 'timeout', 'cancelled', 'pre_check_failed'] as const

const phase = computed<'idle' | 'active' | 'terminal'>(() => {
  if (!props.run) return 'idle'
  if (ACTIVE.includes(props.run.status as any)) return 'active'
  if (TERMINAL.includes(props.run.status as any)) return 'terminal'
  return 'idle'
})

// plan 字段（从 thread_groups_config 算）
const planThreads = computed(() => plannedThreads(props.task.thread_groups_config))
const planRps = computed(() => targetRps(props.task.thread_groups_config))
const onlyArrivals = computed(() => hasOnlyArrivals(props.task.thread_groups_config))

// 当前值取实时序列最后一个点；终态从 TaskRun 汇总字段取（更准）
const currentActiveUsers = computed(() => {
  if (phase.value === 'terminal' && props.run) return props.run.virtual_users || 0
  return lastValue(props.metrics?.overall.active_users)
})
const currentRps = computed(() => {
  if (phase.value === 'terminal' && props.run) return props.run.avg_rps || 0
  return lastValue(props.metrics?.overall.rps)
})
const currentP99 = computed(() => {
  if (phase.value === 'terminal' && props.run) return props.run.p99_ms || 0
  return lastValue(props.metrics?.overall.p99_ms)
})
const currentErrorRate = computed(() => {
  if (phase.value === 'terminal' && props.run) return props.run.error_rate || 0
  return lastValue(props.metrics?.overall.error_rate)
})

interface CardDef {
  label: string
  baseColor: string                   // 默认主色
  decimals: number
  divisorText: () => string           // 副信息（plan / 单位）
  value: () => number                 // 主数字
  isMeaningless?: () => boolean       // 显示 "—" 而不是数字
  finalColor?: () => string           // terminal 时的染色覆盖
}

const CARDS = computed<CardDef[]>(() => [
  {
    label: '活跃线程',
    baseColor: '#3b82f6',
    decimals: 0,
    divisorText: () => (onlyArrivals.value ? 'RPS 驱动' : `/ ${planThreads.value || 0}`),
    value: () => currentActiveUsers.value,
    isMeaningless: () => onlyArrivals.value,
  },
  {
    label: '当前 RPS',
    baseColor: '#8b5cf6',
    decimals: 1,
    divisorText: () => (planRps.value ? `/ ${planRps.value}` : 'req/s'),
    value: () => currentRps.value,
  },
  {
    label: 'P99 响应',
    baseColor: '#ec4899',
    decimals: 0,
    divisorText: () => 'ms',
    value: () => currentP99.value,
  },
  {
    label: '错误率',
    baseColor: '#8b5cf6',
    decimals: 2,
    divisorText: () => '%',
    value: () => currentErrorRate.value,
    finalColor: () => (currentErrorRate.value <= 1 ? '#10b981' : '#ef4444'),
  },
])

function mainColor(def: CardDef): string {
  if (phase.value === 'terminal' && def.finalColor) return def.finalColor()
  // idle 时配色稍淡（70% alpha hex）让水印对比更柔
  return phase.value === 'idle' ? def.baseColor + 'b3' : def.baseColor
}

function formatValue(n: number, decimals: number): string {
  if (!isFinite(n)) return '0'
  if (decimals > 0) return n.toFixed(decimals)
  // 大数字千位分组
  return Math.round(n).toLocaleString()
}

// 水印阶梯：按 KPI 类型给一组典型量级
function tickStops(idx: number): string[] {
  if (idx === 0) {
    const m = planThreads.value
    if (!m) return ['0', '50', '100', '150', '200']
    return [Math.round(m * 0.25), Math.round(m * 0.5), Math.round(m * 0.75), m].map(String)
  }
  if (idx === 1) {
    const t = planRps.value
    if (t) return [Math.round(t * 0.25), Math.round(t * 0.5), Math.round(t * 0.75), t].map(String)
    return ['100', '500', '1k', '2k']
  }
  if (idx === 2) return ['100', '200', '500', '1k']
  return ['0.5', '1', '5', '10']
}
</script>

<template>
  <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
    <Motion
      v-for="(def, i) in CARDS"
      :key="def.label"
      as="div"
      :initial="{ opacity: 0, y: 8 }"
      :animate="{ opacity: 1, y: 0 }"
      :transition="{ duration: 0.5, delay: i * 0.07 }"
      class="relative overflow-hidden rounded-2xl"
      :style="{
        background: isDark ? 'rgba(255,255,255,0.025)' : 'rgba(255,255,255,0.6)',
        border: isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.05)',
        backdropFilter: 'blur(40px)',
        minHeight: '108px',
      }"
    >
      <!-- 主内容 -->
      <div class="relative z-10 px-4 pt-3 pb-3.5 h-full flex flex-col justify-between">
        <div
          class="text-[11px] uppercase tracking-wider font-medium"
          :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }"
        >
          {{ def.label }}
        </div>
        <div class="flex items-baseline gap-2">
          <span
            v-if="def.isMeaningless?.()"
            class="text-[44px] leading-none font-semibold tracking-tight"
            :style="{ color: mainColor(def) }"
          >—</span>
          <span
            v-else
            class="text-[44px] leading-none font-semibold tracking-tight tabular-nums transition-colors duration-300"
            :style="{ color: mainColor(def) }"
          >{{ formatValue(def.value(), def.decimals) }}</span>
          <span
            class="text-[13px] font-medium pb-0.5"
            :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
          >{{ def.divisorText() }}</span>
        </div>
      </div>

      <!-- 水印阶梯数字（绝对定位右半区） -->
      <div
        class="absolute inset-y-0 right-3 flex items-center gap-3 pointer-events-none select-none"
        :style="{ opacity: isDark ? 0.07 : 0.05 }"
      >
        <span
          v-for="n in tickStops(i)"
          :key="n"
          class="font-mono font-semibold tracking-tight"
          :style="{
            fontSize: '36px',
            color: isDark ? '#ffffff' : '#000000',
            lineHeight: 1,
          }"
        >{{ n }}</span>
      </div>
    </Motion>
  </div>
</template>
