<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { SeriesPoint } from '@/types/task'
import HoverTip from './HoverTip.vue'

use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

// spike 场景 图②：请求队列积压深度随时间（面积）。
// 突刺打进来时若处理能力跟不上，请求在队列里堆积；峰值后多久排空 = 系统弹性。
// 需要服务端/网关队列指标（当前 mock 占位）。
const props = defineProps<{
  depth: SeriesPoint[]
  xRange?: [number, number] | null
  isDark: boolean
}>()

const peak = computed(() => props.depth.reduce((m, [, v]) => (v > m ? v : m), 0))
const hasData = computed(() => props.depth.some(([, v]) => v > 0))

const option = computed(() => {
  const axisC = props.isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)'
  const gridLine = props.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'
  const xMin = props.xRange?.[0]
  const xMax = props.xRange?.[1]
  return {
    grid: { left: 50, right: 16, top: 18, bottom: 28 },
    tooltip: {
      trigger: 'axis' as const,
      backgroundColor: props.isDark ? 'rgba(20,20,22,0.92)' : 'rgba(255,255,255,0.95)',
      borderColor: props.isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)',
      textStyle: { color: props.isDark ? '#fff' : '#000', fontSize: 11 },
      valueFormatter: (v: any) => `${Math.round(v)} 待处理`,
    },
    xAxis: {
      type: 'time' as const,
      ...(xMin && xMax ? { min: xMin, max: xMax } : {}),
      axisLine: { lineStyle: { color: axisC } },
      axisLabel: { color: axisC, fontSize: 10 },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value' as const,
      name: '队列深度',
      nameLocation: 'middle' as const,
      nameGap: 36,
      min: 0,
      nameTextStyle: { color: axisC, fontSize: 10 },
      axisLine: { show: false },
      axisLabel: { color: axisC, fontSize: 10 },
      splitLine: { lineStyle: { color: gridLine } },
    },
    series: [
      {
        name: '队列积压', type: 'line' as const,
        smooth: true, symbol: 'none',
        lineStyle: { width: 1.6, color: '#a855f7' },
        areaStyle: { color: '#a855f7', opacity: 0.18 },
        data: props.depth,
      },
    ],
  }
})
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="flex items-center justify-between gap-2 px-1 mb-1">
      <HoverTip
        :tip="'核心问题（峰值）：突刺打进来，请求有没有在队列里堆积？多久排空？\n\n判读：\n· 几乎贴 0 → 处理能力扛得住突刺\n· 峰值飙高但峰后快速回 0 → 短暂排队，弹性 OK\n· 峰后迟迟不回落 → 系统没消化掉积压，可能雪崩\n\n（数据源：网关/服务端队列指标；当前 mock 占位）'"
        :is-dark="isDark"
      >
        <span class="text-[11.5px]" :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }">
          请求队列积压深度
        </span>
      </HoverTip>
      <span v-if="peak" class="text-[10.5px] tabular-nums" :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">
        峰值 {{ Math.round(peak) }}
      </span>
    </div>
    <div class="flex-1 min-h-0">
      <VChart v-if="hasData" :option="option" autoresize style="width: 100%; height: 100%" />
      <div
        v-else
        class="h-full flex items-center justify-center text-[11px]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)' }"
      >待接入服务端监控数据</div>
    </div>
  </div>
</template>
