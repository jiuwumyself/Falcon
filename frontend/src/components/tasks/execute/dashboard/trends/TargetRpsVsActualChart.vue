<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, TitleComponent, LegendComponent, MarkLineComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { SeriesPoint } from '@/types/task'
import HoverTip from './HoverTip.vue'

use([LineChart, GridComponent, TooltipComponent, TitleComponent, LegendComponent, MarkLineComponent, CanvasRenderer])

// throughput 场景末位卡：目标 RPS 红色虚线 + 实际 RPS 实线对比。
// 一眼看出"系统能不能撑住 N qps"。Arrivals TG 配置含 target_rps + unit；
// 转成 per-sec 后画水平虚线。
const props = defineProps<{
  rps: SeriesPoint[]
  targetRpsPerSec: number | null
  xRange?: [number, number] | null
  isDark: boolean
}>()

// 实际 RPS 稳态均值（剔除前 20% ramp 期，跟 ConcurrencyRpsChart steady 同思路）
const actualMean = computed(() => {
  const all = props.rps
  if (!all.length) return 0
  const skip = Math.floor(all.length * 0.2)
  const steady = all.slice(skip)
  if (!steady.length) return 0
  let s = 0
  for (const [, v] of steady) s += v
  return s / steady.length
})

// 达成率：actual / target
const attainmentPct = computed(() => {
  if (!props.targetRpsPerSec || props.targetRpsPerSec <= 0) return null
  if (!actualMean.value) return null
  return (actualMean.value / props.targetRpsPerSec) * 100
})

const hasData = computed(() => props.rps.length > 0)

const option = computed(() => {
  const axisColor = props.isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)'
  const gridLine = props.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'
  const xMin = props.xRange?.[0]
  const xMax = props.xRange?.[1]
  const series: any[] = [
    {
      name: '实际 RPS',
      type: 'line' as const,
      smooth: true,
      symbol: 'none',
      lineStyle: { width: 1.8, color: '#3b82f6' },
      areaStyle: { color: '#3b82f6', opacity: 0.08 },
      data: props.rps,
    },
  ]
  if (props.targetRpsPerSec && props.targetRpsPerSec > 0) {
    series.push({
      name: '目标 RPS',
      type: 'line' as const,
      data: [],
      markLine: {
        symbol: 'none',
        silent: true,
        lineStyle: { color: '#ef4444', type: 'dashed', width: 1.6 },
        label: {
          formatter: `目标 ${props.targetRpsPerSec.toFixed(1)} RPS`,
          color: '#ef4444',
          fontSize: 10,
          position: 'insideEndTop',
        },
        data: [{ yAxis: props.targetRpsPerSec }],
      },
    })
  }
  return {
    grid: { left: 50, right: 18, top: 26, bottom: 30 },
    tooltip: {
      trigger: 'axis' as const,
      backgroundColor: props.isDark ? 'rgba(20,20,22,0.92)' : 'rgba(255,255,255,0.95)',
      borderColor: props.isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)',
      textStyle: { color: props.isDark ? '#fff' : '#000', fontSize: 11 },
    },
    legend: {
      top: 0, right: 0, itemWidth: 10, itemHeight: 8, itemGap: 12,
      textStyle: { color: axisColor, fontSize: 10 },
      data: ['实际 RPS', '目标 RPS'],
    },
    xAxis: {
      type: 'time' as const,
      ...(xMin && xMax ? { min: xMin, max: xMax } : {}),
      axisLine: { lineStyle: { color: axisColor } },
      axisLabel: { color: axisColor, fontSize: 10 },
      splitLine: { show: false },
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
    series,
  }
})

function attainColor(pct: number | null): string {
  if (pct === null) return props.isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)'
  if (pct >= 95) return '#10b981'
  if (pct >= 80) return '#f59e0b'
  return '#ef4444'
}
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="flex items-center justify-between gap-2 px-1 mb-1">
      <HoverTip
        :tip="'核心问题（吞吐量）：要求 N RPS，系统给得动吗？延迟代价多少？\n\n判读条件：\n· 实际线锁在虚线上 → ✅ 目标达成，系统抵得住\n· 实际线一直低于虚线 → ❌ 系统是瓶颈，配合 LatencyChart 看 P99\n· ramp 期慢慢爬到目标 → 正常，检查 ramp_up 是否够长\n· 达成 ≥ 95%（绿）→ 健康；80-95%（黄）→ 紧张；< 80%（红）→ 不达标\n· 实际达成但 ConcurrencyChart 显示 JMeter 用超多 VU → 延迟代价高'"
        :is-dark="isDark"
      >
        <span class="text-[11.5px]"
              :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }">
          目标 RPS vs 实际 RPS
        </span>
      </HoverTip>
      <div
        class="text-[10.5px] tabular-nums"
        :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
      >
        <template v-if="targetRpsPerSec && targetRpsPerSec > 0">
          目标 {{ targetRpsPerSec.toFixed(1) }} · 实际均值 {{ actualMean.toFixed(1) }} ·
          <span :style="{ color: attainColor(attainmentPct) }">
            达成率 {{ attainmentPct !== null ? attainmentPct.toFixed(0) + '%' : '—' }}
          </span>
        </template>
        <template v-else>
          实际均值 {{ actualMean.toFixed(1) }} RPS（无目标基线）
        </template>
      </div>
    </div>
    <div class="flex-1 min-h-0">
      <VChart
        v-if="hasData"
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
