<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { GaugeChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { RunMetricsSeries, SeriesPoint } from '@/types/task'

use([GaugeChart, TitleComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  totals: { total_count: number; total_errors: number } | null
  series: RunMetricsSeries | null
  isDark: boolean
}>()

// 阶梯压力下累计错误率会"骗人"（前期通过 + 后期崩盘平均后看起来很低）。
// gauge 改成最近 60s 滑动窗口的实时错误率，累计值降级成下方小字。
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

function colorFor(pct: number): string {
  if (pct < 0.5) return '#10b981'
  if (pct < 5) return '#f59e0b'
  return '#ef4444'
}

const option = computed(() => {
  const pct = realtimePct.value
  const hasData = pct !== null
  const value = hasData ? pct : 0
  const color = hasData
    ? colorFor(pct)
    : (props.isDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.25)')
  // 显示范围 0..max(1, ceil(value*1.5))，保证小错误率也能看清半圆变化
  const max = Math.max(1, Math.ceil(value * 1.5))
  return {
    series: [
      {
        type: 'gauge' as const,
        startAngle: 200,
        endAngle: -20,
        center: ['50%', '70%'],
        radius: '95%',
        min: 0,
        max,
        progress: {
          show: true,
          width: 14,
          itemStyle: { color },
        },
        axisLine: {
          lineStyle: {
            width: 14,
            color: [[1, props.isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)']],
          },
        },
        pointer: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { show: false },
        anchor: { show: false },
        title: { show: false },
        detail: {
          valueAnimation: true,
          formatter: () => (hasData ? `${value.toFixed(2)}%` : '—'),
          fontSize: 26,
          color,
          offsetCenter: [0, '0%'],
        },
        data: [{ value }],
      },
    ],
  }
})

const cumulativeText = computed(() => {
  const v = cumulativePct.value
  return v === null ? '—' : `${v.toFixed(2)}%`
})
</script>

<template>
  <div class="flex flex-col h-full">
    <div
      class="text-[11.5px] mb-1 px-1"
      :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }"
    >
      实时错误率（60s 窗口）
    </div>
    <div class="flex-1 min-h-0 relative">
      <VChart :option="option" autoresize style="width: 100%; height: 100%" />
    </div>
    <div
      class="text-[10.5px] text-center pb-1"
      :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }"
    >
      累计 {{ cumulativeText }}
    </div>
  </div>
</template>
