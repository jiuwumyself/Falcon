<script setup lang="ts">
import { computed } from 'vue'
import type { RunMetricsSeries, RunMetricsTotals, SeriesPoint } from '@/types/task'
import { fmtBytesTotal, fmtInt } from './chartFactory'
import { colorForErrorMetric, SEMANTIC } from './semanticColors'

// 双行 KPI：上行"当前"（看一眼现在怎么样）/ 下行"累计"（整 run 沉淀指标）
const props = defineProps<{
  totals: RunMetricsTotals | null
  series: RunMetricsSeries | null
  isDark: boolean
}>()

function lastOf(pts: SeriesPoint[] | undefined): number | null {
  if (!pts || !pts.length) return null
  return pts[pts.length - 1][1]
}

// 实时错误率：跟 ErrorRateGauge 用同一算法，最近 60s 窗口
function lastWindowRate(
  errorPts: SeriesPoint[] | undefined,
  rpsPts: SeriesPoint[] | undefined,
  windowMs = 60_000,
): number | null {
  if (!errorPts?.length || !rpsPts?.length) return null
  const now = Math.max(
    errorPts[errorPts.length - 1][0],
    rpsPts[rpsPts.length - 1][0],
  )
  const cutoff = now - windowMs
  let errSum = 0
  let reqSum = 0
  for (const [t, v] of errorPts) if (t >= cutoff) errSum += v
  for (const [t, v] of rpsPts) if (t >= cutoff) reqSum += v
  if (reqSum === 0) return null
  return (errSum / reqSum) * 100
}

function fmtNum(v: number | null, suffix = '', digits = 0): string {
  if (v === null) return '—'
  return v.toFixed(digits) + suffix
}

const primary = computed(() => props.isDark ? 'rgba(255,255,255,0.92)' : 'rgba(0,0,0,0.85)')

// 颜色策略：异常态（> 0）才染红，正常态用主色
// 让红色专属异常 —— 红色一出现立刻劈开视觉，比"绿/红双饱和"更易感知
function errColor(v: number | null, threshold = 0): string {
  return colorForErrorMetric(v, primary.value, threshold)
}

const currentRow = computed(() => {
  const s = props.series
  const vu = lastOf(s?.active_users)
  const rps = lastOf(s?.rps)
  const p95 = lastOf(s?.p95_ms)
  const errPct = lastWindowRate(s?.error_count, s?.rps)
  return [
    { label: '现在 · 并发', value: fmtNum(vu, '', 0), color: primary.value },
    { label: '现在 · RPS', value: fmtNum(rps, '', 1), color: primary.value },
    { label: '现在 · P95', value: fmtNum(p95, ' ms', 0), color: primary.value },
    { label: '现在 · 实时错误率', value: errPct === null ? '—' : errPct.toFixed(2) + '%', color: errColor(errPct) },
  ]
})

const cumulativeRow = computed(() => {
  const t = props.totals
  const totalCount = t?.total_count ?? 0
  const totalErrors = t?.total_errors ?? 0
  const recv = t?.total_bytes_recv ?? 0
  const sent = t?.total_bytes_sent ?? 0
  return [
    { label: '累计 · 总请求数', value: fmtInt(totalCount), color: primary.value },
    { label: '累计 · 失败数', value: fmtInt(totalErrors), color: totalErrors > 0 ? SEMANTIC.errors : primary.value },
    { label: '累计 · 接收字节', value: fmtBytesTotal(recv), color: primary.value },
    { label: '累计 · 发送字节', value: fmtBytesTotal(sent), color: primary.value },
  ]
})

const cardStyle = computed(() => ({
  background: props.isDark ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.7)',
  border: props.isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.06)',
}))
</script>

<template>
  <div class="flex flex-col gap-2">
    <!-- 上行：当前（雷达视角，性能老炮看"现在崩了没"用） -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <div
        v-for="c in currentRow"
        :key="c.label"
        class="rounded-xl px-4 py-2.5 flex flex-col items-center justify-center"
        :style="cardStyle"
      >
        <div
          class="text-[10.5px] tracking-wide mb-1"
          :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.55)' }"
        >
          {{ c.label }}
        </div>
        <div
          class="text-[24px] font-semibold leading-none tabular-nums"
          :style="{ color: c.color }"
        >
          {{ c.value }}
        </div>
      </div>
    </div>
    <!-- 下行：累计（沉淀视角，看"整 run 跑了多少") -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <div
        v-for="c in cumulativeRow"
        :key="c.label"
        class="rounded-xl px-4 py-2.5 flex flex-col items-center justify-center"
        :style="cardStyle"
      >
        <div
          class="text-[10.5px] tracking-wide mb-1"
          :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.5)' }"
        >
          {{ c.label }}
        </div>
        <div
          class="text-[20px] font-semibold leading-none tabular-nums"
          :style="{ color: c.color }"
        >
          {{ c.value }}
        </div>
      </div>
    </div>
    <!-- 数据源标签 -->
    <div
      class="text-[10.5px] text-right pr-1"
      :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
    >
      基于 InfluxDB 实时聚合（终态后以 JTL 为准）
    </div>
  </div>
</template>
