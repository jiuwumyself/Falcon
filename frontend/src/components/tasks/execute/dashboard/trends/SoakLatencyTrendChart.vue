<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, TitleComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { SeriesPoint } from '@/types/task'

use([LineChart, GridComponent, TooltipComponent, TitleComponent, CanvasRenderer])

// soak（稳定性）末位图：RT(p95) 随时间 + 最小二乘回归趋势线。
// 为什么不用 RPS 趋势：稳定性测试最常见的失败信号是 **RT 缓慢爬升**（内存泄漏 →
// GC 压力 → 延迟升），RPS 往往还能保持平稳。盯 RPS 会漏掉这种 leak。这里把回归
// 线打在 p95 RT 上，斜率 > 0 = 长跑衰减。p95 兼顾 SLA 意义 + 抓尾部退化，比 p50 敏感、
// 比 p99 稳。
const props = defineProps<{
  lat: SeriesPoint[]
  isDark: boolean
  xRange?: [number, number] | null
}>()

interface Trend { slopePerMin: number; t0: number; t1: number; y0: number; y1: number }

// 最小二乘回归 over (秒, ms)。返回端点 + 每分钟斜率（ms/min）。
const trend = computed<Trend | null>(() => {
  const pts = props.lat.filter(([, v]) => v > 0)
  if (pts.length < 3) return null
  const t0 = pts[0][0]
  const xs = pts.map(([t]) => (t - t0) / 1000)
  const ys = pts.map(([, v]) => v)
  const n = xs.length
  const xbar = xs.reduce((a, b) => a + b, 0) / n
  const ybar = ys.reduce((a, b) => a + b, 0) / n
  let num = 0
  let den = 0
  for (let i = 0; i < n; i++) {
    num += (xs[i] - xbar) * (ys[i] - ybar)
    den += (xs[i] - xbar) ** 2
  }
  if (den === 0) return null
  const slopePerSec = num / den
  const intercept = ybar - slopePerSec * xbar
  const lastX = xs[n - 1]
  return {
    slopePerMin: slopePerSec * 60,
    t0,
    t1: pts[n - 1][0],
    y0: intercept,
    y1: intercept + slopePerSec * lastX,
  }
})

// 判定：整段相对漂移 = (终点回归值 - 起点回归值) / 起点回归值。>10% 上升 → 疑似衰减。
const verdict = computed(() => {
  const tr = trend.value
  if (!tr || tr.y0 <= 0) return null
  const drift = (tr.y1 - tr.y0) / tr.y0
  if (drift > 0.1) {
    return { text: `RT 上升 ${(drift * 100).toFixed(0)}%（${tr.slopePerMin.toFixed(1)} ms/min）— 疑似资源衰减 / 泄漏`, color: '#f59e0b' }
  }
  if (drift < -0.1) {
    return { text: `RT 下降 ${(-drift * 100).toFixed(0)}%（${tr.slopePerMin.toFixed(1)} ms/min）— 预热后趋稳`, color: '#10b981' }
  }
  return { text: `RT 平稳（${tr.slopePerMin >= 0 ? '+' : ''}${tr.slopePerMin.toFixed(1)} ms/min）`, color: '#10b981' }
})

const hasData = computed(() => props.lat.some(([, v]) => v > 0))

const option = computed(() => {
  const axisColor = props.isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)'
  const gridLine = props.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'
  const series: any[] = [
    {
      name: 'p95 RT',
      type: 'line' as const,
      showSymbol: false,
      smooth: true,
      data: props.lat,
      lineStyle: { color: props.isDark ? 'rgba(168,85,247,0.9)' : 'rgba(124,58,237,0.9)', width: 1.6 },
      areaStyle: { color: props.isDark ? 'rgba(168,85,247,0.12)' : 'rgba(124,58,237,0.08)' },
      z: 2,
    },
  ]
  const tr = trend.value
  if (tr) {
    series.push({
      name: '趋势',
      type: 'line' as const,
      showSymbol: false,
      data: [[tr.t0, tr.y0], [tr.t1, tr.y1]],
      lineStyle: { color: '#f59e0b', width: 1.6, type: 'dashed' },
      tooltip: { show: false },
      z: 3,
    })
  }
  return {
    grid: { left: 50, right: 18, top: 18, bottom: 38 },
    tooltip: {
      trigger: 'axis' as const,
      formatter: (ps: any) => {
        const p = ps[0]
        const d = new Date(p.value[0])
        const hh = String(d.getHours()).padStart(2, '0')
        const mm = String(d.getMinutes()).padStart(2, '0')
        const ss = String(d.getSeconds()).padStart(2, '0')
        return `${hh}:${mm}:${ss}<br/>p95 RT ${p.value[1].toFixed(0)} ms`
      },
      backgroundColor: props.isDark ? 'rgba(20,20,22,0.92)' : 'rgba(255,255,255,0.95)',
      borderColor: props.isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)',
      textStyle: { color: props.isDark ? '#fff' : '#000', fontSize: 11 },
    },
    xAxis: {
      type: 'time' as const,
      name: '时间',
      nameLocation: 'middle' as const,
      nameGap: 24,
      min: props.xRange?.[0] ?? undefined,
      max: props.xRange?.[1] ?? undefined,
      nameTextStyle: { color: axisColor, fontSize: 10 },
      axisLine: { lineStyle: { color: axisColor } },
      axisLabel: { color: axisColor, fontSize: 10 },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value' as const,
      name: 'p95 RT (ms)',
      nameLocation: 'middle' as const,
      nameGap: 38,
      nameTextStyle: { color: axisColor, fontSize: 10 },
      axisLine: { lineStyle: { color: axisColor } },
      axisLabel: { color: axisColor, fontSize: 10 },
      splitLine: { lineStyle: { color: gridLine } },
    },
    series,
  }
})
</script>

<template>
  <div class="flex flex-col h-full">
    <div
      v-if="verdict"
      class="text-[10.5px] px-2 py-0.5 mb-1 rounded inline-flex items-center gap-1 self-start"
      :style="{ background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)', color: verdict.color }"
    >
      {{ verdict.text }}
    </div>
    <div class="flex-1 min-h-0">
      <VChart v-if="hasData" :option="option" autoresize />
      <div
        v-else
        class="h-full flex items-center justify-center text-[11px]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.4)' }"
      >
        暂无延迟数据
      </div>
    </div>
  </div>
</template>
