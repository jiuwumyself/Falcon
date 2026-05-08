<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TitleComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { RunMetricsSeries, SeriesPoint } from '@/types/task'
import { colorForErrorRate } from './semanticColors'

use([LineChart, GridComponent, TitleComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  totals: { total_count: number; total_errors: number } | null
  series: RunMetricsSeries | null
  isDark: boolean
}>()

// 中心大数字 = 最近 60s 滚动错误率（与累计区分；阶梯压力下不"骗人"）
function lastWindowRate(
  errorPts: SeriesPoint[],
  rpsPts: SeriesPoint[],
  windowMs = 60_000,
): number | null {
  if (!errorPts.length || !rpsPts.length) return null
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

const realtimePct = computed(() =>
  lastWindowRate(
    props.series?.error_count || [],
    props.series?.rps || [],
  ),
)

const cumulativePct = computed(() => {
  const t = props.totals
  if (!t || !t.total_count) return null
  return (t.total_errors / t.total_count) * 100
})

const themedColor = computed(() => {
  const pct = realtimePct.value
  if (pct === null) return props.isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.4)'
  return colorForErrorRate(pct)
})

// sparkline 数据：取 series.error_rate 最后 60 个点（每秒瞬时错误率，0-1 比率 → ×100 转 %）
const sparklineData = computed<SeriesPoint[]>(() => {
  const pts = props.series?.error_rate || []
  if (!pts.length) return []
  return pts.slice(-60).map(([t, v]) => [t, v * 100])
})

const sparklineOption = computed(() => {
  const data = sparklineData.value
  const color = themedColor.value
  return {
    grid: { left: 0, right: 0, top: 2, bottom: 2 },
    xAxis: { type: 'time' as const, show: false },
    yAxis: { type: 'value' as const, show: false, min: 0 },
    tooltip: {
      trigger: 'axis' as const,
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params
        return `${p.value[1].toFixed(2)}%`
      },
      backgroundColor: props.isDark ? 'rgba(20,20,22,0.92)' : 'rgba(255,255,255,0.95)',
      borderColor: props.isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)',
      textStyle: { color: props.isDark ? '#fff' : '#000', fontSize: 11 },
      axisPointer: { type: 'line' as const, lineStyle: { color: 'rgba(120,120,120,0.3)' } },
    },
    series: [
      {
        type: 'line' as const,
        data,
        showSymbol: false,
        smooth: true,
        sampling: 'lttb' as const,
        lineStyle: { width: 1.5, color },
        areaStyle: { color, opacity: 0.18 },
      },
    ],
  }
})

const realtimeText = computed(() => {
  const v = realtimePct.value
  return v === null ? '—' : `${v.toFixed(2)}%`
})

const cumulativeText = computed(() => {
  const v = cumulativePct.value
  return v === null ? '—' : `${v.toFixed(2)}%`
})
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="flex items-center justify-between px-1 mb-1">
      <div
        class="text-[11.5px]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }"
      >
        实时错误率（60s 窗口）
      </div>
      <div
        class="text-[10.5px] tabular-nums"
        :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
      >
        累计 {{ cumulativeText }}
      </div>
    </div>
    <!-- 大数字 -->
    <div class="flex-1 flex items-center justify-center">
      <span
        class="text-[34px] font-semibold leading-none tabular-nums"
        :style="{ color: themedColor }"
      >
        {{ realtimeText }}
      </span>
    </div>
    <!-- sparkline：最近 60s 瞬时错误率，让用户看到"是冲上去的还是稳定的" -->
    <div v-if="sparklineData.length" class="h-[36px]">
      <VChart :option="sparklineOption" autoresize style="width: 100%; height: 100%" />
    </div>
    <div v-else class="h-[36px]" />
  </div>
</template>
