<script setup lang="ts">
import { computed } from 'vue'
import { Activity, AlertTriangle, Clock, Flag, FastForward, AlertOctagon } from 'lucide-vue-next'
import type { RunEvent, RunEventType, TaskRun } from '@/types/task'

// § 12 S1：run 关键事件锚点的水平时间轴。事件按 ts_ms 投影到 [run.started_at, end_ts]
// 区间，画圆点 + 文字标签。run 还在跑 / 事件空时不渲染（return null）。
//
// chart 内部 markLine 留 v2（要扩 chartFactory.buildSeriesOption）；先用独立组件
// 保证 schema 落地不阻塞 chart 重构节奏。

const props = defineProps<{
  events: RunEvent[]
  run: TaskRun | null
  isDark: boolean
}>()

const META: Record<RunEventType, { label: string; color: string; icon: any }> = {
  ramp_done: { label: 'ramp 完成', color: '#3b82f6', icon: FastForward },
  hold_start: { label: 'hold 开始', color: '#10b981', icon: Flag },
  shutdown_start: { label: 'shutdown', color: '#9ca3af', icon: Clock },
  first_error: { label: '首次错误', color: '#f59e0b', icon: AlertTriangle },
  error_rate_breached: { label: '错误率告警', color: '#ef4444', icon: AlertOctagon },
  p99_sla_breached: { label: 'P99 破 SLA', color: '#ef4444', icon: Activity },
}

const startMs = computed<number | null>(() => {
  const s = props.run?.started_at
  return s ? new Date(s).getTime() : null
})
const endMs = computed<number | null>(() => {
  const r = props.run
  if (!r) return null
  if (r.finished_at) return new Date(r.finished_at).getTime()
  return Date.now()  // 运行中
})

const hasData = computed(() => {
  return startMs.value && endMs.value && endMs.value > startMs.value && props.events.length > 0
})

// 投影到 0-100 % 区间
const positioned = computed(() => {
  if (!startMs.value || !endMs.value) return []
  const start = startMs.value
  const end = endMs.value
  const span = end - start
  if (span <= 0) return []
  return props.events.map((e) => ({
    event: e,
    leftPct: Math.max(0, Math.min(100, ((e.ts_ms - start) / span) * 100)),
    meta: META[e.event_type] ?? META.first_error,
  })).sort((a, b) => a.leftPct - b.leftPct)
})

function fmtTime(ms: number): string {
  const d = new Date(ms)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}
</script>

<template>
  <div
    v-if="hasData"
    class="rounded-xl px-3 py-2.5"
    :style="{
      background: isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)',
      border: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
    }"
  >
    <div
      class="flex items-center gap-1.5 mb-2 text-[11px]"
      :style="{ color: isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.55)' }"
    >
      <Flag :size="11" />
      <span>关键事件锚点（{{ events.length }}）</span>
      <span class="ml-auto text-[10px] opacity-60">
        {{ run?.started_at ? fmtTime(new Date(run.started_at).getTime()) : '' }}
        →
        {{ run?.finished_at ? fmtTime(new Date(run.finished_at).getTime()) : '运行中' }}
      </span>
    </div>

    <div class="relative h-[42px]">
      <!-- 时间轴线 -->
      <div
        class="absolute left-0 right-0 top-1/2 h-px"
        :style="{ background: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)' }"
      />
      <!-- 事件圆点 + 标签 -->
      <div
        v-for="(p, i) in positioned"
        :key="i"
        class="absolute top-0 h-full flex flex-col items-center"
        :style="{ left: `calc(${p.leftPct}% - 6px)`, transform: 'translateY(0)' }"
        :title="`${p.meta.label} @ ${fmtTime(p.event.ts_ms)}`"
      >
        <!-- 上方 label，奇偶上下交替避免重叠 -->
        <div
          v-if="i % 2 === 0"
          class="text-[9.5px] tabular-nums leading-none mb-0.5 whitespace-nowrap"
          :style="{ color: p.meta.color }"
        >
          {{ p.meta.label }}
        </div>
        <div v-else style="height: 11px" />
        <!-- 圆点 -->
        <div
          class="w-3 h-3 rounded-full flex items-center justify-center"
          :style="{
            background: p.meta.color,
            border: `2px solid ${isDark ? '#0a0a0a' : '#fff'}`,
          }"
        />
        <!-- 下方 label -->
        <div
          v-if="i % 2 === 1"
          class="text-[9.5px] tabular-nums leading-none mt-0.5 whitespace-nowrap"
          :style="{ color: p.meta.color }"
        >
          {{ p.meta.label }}
        </div>
        <div v-else style="height: 11px" />
      </div>
    </div>
  </div>
</template>
