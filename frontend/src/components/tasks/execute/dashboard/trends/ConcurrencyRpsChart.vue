<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { ScatterChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, TitleComponent, VisualMapComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { SeriesPoint } from '@/types/task'

use([ScatterChart, GridComponent, TooltipComponent, TitleComponent, VisualMapComponent, CanvasRenderer])

// 并发-RPS 关系散点图：横轴并发 VU / 纵轴 RPS / 每个时间点一个散点
// 用时间维度做 visualMap 颜色梯度（早期淡 → 后期深），看出压力推进路径
// 一眼看出：线性增长 / 平台期 / 性能拐点 / 系统崩盘
const props = defineProps<{
  rps: SeriesPoint[]
  vu: SeriesPoint[]
  isDark: boolean
}>()

interface ScatterPoint { vu: number; rps: number; ts: number }

// 按 timestamp 对齐两条序列，O(N+M) 双指针
const points = computed<ScatterPoint[]>(() => {
  if (!props.rps.length || !props.vu.length) return []
  const rpsMap = new Map<number, number>()
  for (const [t, v] of props.rps) rpsMap.set(t, v)
  const out: ScatterPoint[] = []
  for (const [t, vu] of props.vu) {
    if (vu <= 0) continue
    const r = rpsMap.get(t)
    if (r == null) continue
    out.push({ vu, rps: r, ts: t })
  }
  return out
})

const tsRange = computed(() => {
  const pts = points.value
  if (!pts.length) return [0, 0]
  return [pts[0].ts, pts[pts.length - 1].ts]
})

const option = computed(() => {
  const pts = points.value
  const data = pts.map((p) => [p.vu, p.rps, p.ts])
  const [tsMin, tsMax] = tsRange.value
  const axisColor = props.isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)'
  const gridLine = props.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'
  return {
    grid: { left: 50, right: 18, top: 18, bottom: 38 },
    tooltip: {
      trigger: 'item' as const,
      formatter: (p: any) => {
        const [vu, rps, ts] = p.value
        const date = new Date(ts)
        const hh = String(date.getHours()).padStart(2, '0')
        const mm = String(date.getMinutes()).padStart(2, '0')
        const ss = String(date.getSeconds()).padStart(2, '0')
        return `${hh}:${mm}:${ss}<br/>并发 ${vu} VU<br/>吞吐 ${rps.toFixed(1)} req/s`
      },
      backgroundColor: props.isDark ? 'rgba(20,20,22,0.92)' : 'rgba(255,255,255,0.95)',
      borderColor: props.isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)',
      textStyle: { color: props.isDark ? '#fff' : '#000', fontSize: 11 },
    },
    visualMap: {
      show: false,
      min: tsMin,
      max: tsMax,
      dimension: 2,    // 用第三维（ts）做颜色映射
      inRange: {
        color: props.isDark
          ? ['rgba(168,85,247,0.25)', 'rgba(168,85,247,0.95)']
          : ['rgba(168,85,247,0.20)', 'rgba(124,58,237,0.95)'],
      },
    },
    xAxis: {
      type: 'value' as const,
      name: '并发 VU',
      nameLocation: 'middle' as const,
      nameGap: 24,
      nameTextStyle: { color: axisColor, fontSize: 10 },
      axisLine: { lineStyle: { color: axisColor } },
      axisLabel: { color: axisColor, fontSize: 10 },
      splitLine: { lineStyle: { color: gridLine } },
    },
    yAxis: {
      type: 'value' as const,
      name: 'RPS',
      nameLocation: 'middle' as const,
      nameGap: 38,
      nameTextStyle: { color: axisColor, fontSize: 10 },
      axisLine: { lineStyle: { color: axisColor } },
      axisLabel: { color: axisColor, fontSize: 10 },
      splitLine: { lineStyle: { color: gridLine } },
    },
    series: [
      {
        type: 'scatter' as const,
        symbolSize: 6,
        data,
        emphasis: { focus: 'self' as const },
      },
    ],
  }
})

// 排除前几秒 ramp-up（VU 从 0 爬到目标）的样本，避免它们扰动"恒定并发"判定
function steadyStatePoints(pts: ScatterPoint[]): ScatterPoint[] {
  if (pts.length <= 5) return pts
  let maxVu = 0
  for (const p of pts) if (p.vu > maxVu) maxVu = p.vu
  // 取已经爬到 80% 目标 VU 之后的点
  const threshold = maxVu * 0.8
  const steady = pts.filter((p) => p.vu >= threshold)
  return steady.length >= 5 ? steady : pts
}

const summary = computed(() => {
  const all = points.value
  if (!all.length) return null
  const pts = steadyStatePoints(all)

  // VU 抖动：max-min 跟 mean 比，判定"恒定并发"场景（稳定性测试）
  let vuMin = Infinity
  let vuMax = 0
  let vuSum = 0
  for (const p of pts) {
    if (p.vu < vuMin) vuMin = p.vu
    if (p.vu > vuMax) vuMax = p.vu
    vuSum += p.vu
  }
  const vuMean = vuSum / pts.length
  // 稳定态 VU 变化 < 10% → 视作"恒定并发"
  const isFlatVu = vuMean > 0 && (vuMax - vuMin) / vuMean < 0.1

  // RPS 统计
  let rpsSum = 0
  let rpsMax = 0
  let peakRpsAtVu = 0
  let maxVu = 0
  let rpsAtMaxVu = 0
  const rpsArr: number[] = []
  for (const p of pts) {
    rpsSum += p.rps
    rpsArr.push(p.rps)
    if (p.rps > rpsMax) {
      rpsMax = p.rps
      peakRpsAtVu = p.vu
    }
    if (p.vu > maxVu) {
      maxVu = p.vu
      rpsAtMaxVu = p.rps
    }
  }
  const rpsMean = rpsSum / pts.length
  // 标准差
  let varSum = 0
  for (const r of rpsArr) varSum += (r - rpsMean) ** 2
  const rpsStd = Math.sqrt(varSum / pts.length)
  // 变异系数（CV = std/mean），衡量抖动幅度
  const rpsCv = rpsMean > 0 ? rpsStd / rpsMean : 0
  // P95
  const sortedRps = [...rpsArr].sort((a, b) => a - b)
  const rpsP95 = sortedRps[Math.floor(sortedRps.length * 0.95)] || rpsMax

  // 降级判定（仅压力梯度场景才有意义；恒定并发时 peakRpsAtVu === maxVu，自然 false）
  const degraded = peakRpsAtVu < maxVu && rpsAtMaxVu < rpsMax * 0.9

  return {
    isFlatVu,
    vuMean,
    peakRps: rpsMax,
    peakRpsAtVu,
    maxVu,
    rpsAtMaxVu,
    degraded,
    rpsMean,
    rpsStd,
    rpsCv,
    rpsP95,
  }
})
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="flex items-center justify-between px-1 mb-1">
      <div
        class="text-[11.5px]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }"
        :title="summary?.isFlatVu
          ? `并发恒定 ${Math.round(summary.vuMean)} VU（稳定性测试场景）—— 散点坍缩成竖线，看 RPS 抖动统计；时序看上方 RPS 大图`
          : '散点 = 时间点 (VU, RPS)；颜色越深越靠后；线性增长 → 平台期 → 性能拐点 / 崩盘'"
      >
        {{ summary?.isFlatVu ? 'RPS 抖动（并发恒定）' : '并发-吞吐关系' }}
      </div>
      <div
        v-if="summary"
        class="text-[10.5px] tabular-nums"
        :style="{
          color: summary.degraded
            ? '#ef4444'
            : (isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)'),
        }"
      >
        <template v-if="summary.isFlatVu">
          {{ Math.round(summary.vuMean) }} VU · 均值 {{ summary.rpsMean.toFixed(0) }} ·
          抖动 ±{{ summary.rpsStd.toFixed(0) }} ({{ (summary.rpsCv * 100).toFixed(1) }}%) ·
          P95 {{ summary.rpsP95.toFixed(0) }}
        </template>
        <template v-else-if="summary.degraded">
          ⚠ 加 VU 不涨吞吐（峰值 {{ summary.peakRps.toFixed(0) }} @ {{ summary.peakRpsAtVu }} VU）
        </template>
        <template v-else>
          峰值 {{ summary.peakRps.toFixed(0) }} req/s @ {{ summary.peakRpsAtVu }} VU
        </template>
      </div>
    </div>
    <div class="flex-1 min-h-0">
      <VChart
        v-if="points.length"
        :option="option"
        autoresize
        style="width: 100%; height: 100%"
      />
      <div
        v-else
        class="h-full flex items-center justify-center text-[11px]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)' }"
      >
        暂无数据
      </div>
    </div>
  </div>
</template>
