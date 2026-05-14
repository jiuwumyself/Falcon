<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, TitleComponent, LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { SeriesPoint } from '@/types/task'
import HoverTip from './HoverTip.vue'

use([LineChart, GridComponent, TooltipComponent, TitleComponent, LegendComponent, CanvasRenderer])

// spike 场景末位卡：VU 与 RPS 共享 x 轴时间，双 y 轴对比。
// 看突冲（5s 起冲）→ hold（60s）→ 退出（5s）阶段 RPS 是否跟随 VU。
// 散点图把时间维压扁了，spike 时间窗短（~70s），双轴时序更能看跟随性。
const props = defineProps<{
  rps: SeriesPoint[]
  vu: SeriesPoint[]
  xRange?: [number, number] | null
  isDark: boolean
}>()

const peakVu = computed(() => props.vu.reduce((m, [, v]) => v > m ? v : m, 0))
const peakRps = computed(() => props.rps.reduce((m, [, v]) => v > m ? v : m, 0))

// 跟随性度量：vu 爬到 80% 峰值时 RPS 达到峰值 RPS 的百分比
const followRatio = computed(() => {
  if (!peakVu.value || !peakRps.value) return null
  const target = peakVu.value * 0.8
  // 找 VU 首次 >= target 的时刻
  const vuMap = props.vu
  let crossT = 0
  for (const [t, v] of vuMap) {
    if (v >= target) { crossT = t; break }
  }
  if (!crossT) return null
  // 看 crossT 那一刻 RPS 是多少（取最近时间戳）
  let nearestRps = 0
  let nearestDt = Infinity
  for (const [t, v] of props.rps) {
    const dt = Math.abs(t - crossT)
    if (dt < nearestDt) { nearestDt = dt; nearestRps = v }
  }
  if (!peakRps.value) return null
  return nearestRps / peakRps.value
})

const hasData = computed(() => props.rps.length > 0 && props.vu.length > 0)

const option = computed(() => {
  const axisColor = props.isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)'
  const gridLine = props.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'
  const xMin = props.xRange?.[0]
  const xMax = props.xRange?.[1]
  return {
    grid: { left: 56, right: 56, top: 26, bottom: 30 },
    tooltip: {
      trigger: 'axis' as const,
      backgroundColor: props.isDark ? 'rgba(20,20,22,0.92)' : 'rgba(255,255,255,0.95)',
      borderColor: props.isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)',
      textStyle: { color: props.isDark ? '#fff' : '#000', fontSize: 11 },
    },
    legend: {
      top: 0, right: 0, itemWidth: 10, itemHeight: 8, itemGap: 12,
      textStyle: { color: axisColor, fontSize: 10 },
    },
    xAxis: {
      type: 'time' as const,
      ...(xMin && xMax ? { min: xMin, max: xMax } : {}),
      axisLine: { lineStyle: { color: axisColor } },
      axisLabel: { color: axisColor, fontSize: 10 },
      splitLine: { show: false },
    },
    yAxis: [
      {
        type: 'value' as const,
        name: 'VU',
        position: 'left' as const,
        nameLocation: 'middle' as const,
        nameGap: 40,
        nameTextStyle: { color: axisColor, fontSize: 10 },
        axisLine: { show: true, lineStyle: { color: '#94a3b8' } },
        axisLabel: { color: axisColor, fontSize: 10 },
        splitLine: { lineStyle: { color: gridLine } },
      },
      {
        type: 'value' as const,
        name: 'RPS',
        position: 'right' as const,
        nameLocation: 'middle' as const,
        nameGap: 40,
        nameTextStyle: { color: axisColor, fontSize: 10 },
        axisLine: { show: true, lineStyle: { color: '#3b82f6' } },
        axisLabel: { color: axisColor, fontSize: 10 },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: 'VU',
        type: 'line' as const,
        yAxisIndex: 0,
        step: 'end' as const,
        symbol: 'none',
        lineStyle: { width: 2, color: '#94a3b8' },
        areaStyle: { color: '#94a3b8', opacity: 0.12 },
        data: props.vu,
      },
      {
        name: 'RPS',
        type: 'line' as const,
        yAxisIndex: 1,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 1.6, color: '#3b82f6' },
        data: props.rps,
      },
    ],
  }
})
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="flex items-center justify-between gap-2 px-1 mb-1">
      <HoverTip
        :tip="'核心问题（峰值）：5s 冲高时 RPS 跟没跟上 + 60s hold 是否平稳 + 退出后 RPS 衰减是否符合\n\n判读条件：\n· VU 起冲瞬间 RPS 同步起 → 响应快，连接池预热充分\n· VU 达峰但 RPS 仍在爬 → 冷启动延迟，连接池/缓存未 warm\n· VU 退出后 RPS 还在出 → 队列堆积，请求排队\n· Hold 期 RPS 不平 → 系统抖动，可能 GC 撞\n· 跟随率 ≥ 80%（绿）→ 健康；50-80%（黄）→ 慢；< 50%（红）→ 严重滞后'"
        :is-dark="isDark"
      >
        <span class="text-[11.5px]"
              :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }">
          VU / RPS 跟随性（双轴对比）
        </span>
      </HoverTip>
      <div
        class="text-[10.5px] tabular-nums"
        :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
      >
        <span v-if="peakVu">峰值 {{ Math.round(peakVu) }} VU · {{ peakRps.toFixed(0) }} RPS</span>
        <span
          v-if="followRatio !== null"
          :style="{ color: followRatio >= 0.8 ? '#10b981' : (followRatio >= 0.5 ? '#f59e0b' : '#ef4444') }"
          class="ml-2"
        >· 跟随率 {{ (followRatio * 100).toFixed(0) }}%</span>
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
