<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { SeriesPoint } from '@/types/task'
import HoverTip from './HoverTip.vue'

use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

// soak 场景 图②：堆内存(MB) + 文件句柄数 双轴随时间。
// 稳定性测试最怕「资源单调爬升不回收」——堆内存锯齿但整体上扬 / 句柄只增不减 =
// 内存或句柄泄漏。需要被测服务端监控数据（当前 mock 占位）。
const props = defineProps<{
  heap: SeriesPoint[]
  handles: SeriesPoint[]
  xRange?: [number, number] | null
  isDark: boolean
}>()

// 句柄整段净增（>0 且明显 = 疑似句柄泄漏）
const handleDrift = computed(() => {
  const h = props.handles
  if (h.length < 2) return null
  return h[h.length - 1][1] - h[0][1]
})
const verdict = computed(() => {
  const d = handleDrift.value
  if (d === null) return null
  if (d > 100) return { text: `句柄净增 ${d} — 疑似句柄/连接泄漏`, color: '#f59e0b' }
  return { text: `句柄净增 ${d}`, color: '#10b981' }
})

const hasData = computed(() => props.heap.length > 0 || props.handles.length > 0)

const option = computed(() => {
  const axisC = props.isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)'
  const gridLine = props.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'
  const xMin = props.xRange?.[0]
  const xMax = props.xRange?.[1]
  return {
    grid: { left: 52, right: 52, top: 26, bottom: 28 },
    tooltip: {
      trigger: 'axis' as const,
      backgroundColor: props.isDark ? 'rgba(20,20,22,0.92)' : 'rgba(255,255,255,0.95)',
      borderColor: props.isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)',
      textStyle: { color: props.isDark ? '#fff' : '#000', fontSize: 11 },
    },
    legend: {
      top: 0, right: 0, itemWidth: 10, itemHeight: 8, itemGap: 12,
      textStyle: { color: axisC, fontSize: 10 },
      data: ['堆内存 MB', '文件句柄'],
    },
    xAxis: {
      type: 'time' as const,
      ...(xMin && xMax ? { min: xMin, max: xMax } : {}),
      axisLine: { lineStyle: { color: axisC } },
      axisLabel: { color: axisC, fontSize: 10 },
      splitLine: { show: false },
    },
    yAxis: [
      {
        type: 'value' as const, name: 'MB', position: 'left' as const,
        nameTextStyle: { color: '#ef4444', fontSize: 10 },
        axisLine: { show: true, lineStyle: { color: '#ef4444' } },
        axisLabel: { color: axisC, fontSize: 10 },
        splitLine: { lineStyle: { color: gridLine } },
      },
      {
        type: 'value' as const, name: '句柄', position: 'right' as const,
        nameTextStyle: { color: '#f59e0b', fontSize: 10 },
        axisLine: { show: true, lineStyle: { color: '#f59e0b' } },
        axisLabel: { color: axisC, fontSize: 10 },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '堆内存 MB', type: 'line' as const, yAxisIndex: 0,
        smooth: false, symbol: 'none',
        lineStyle: { width: 1.6, color: '#ef4444' },
        areaStyle: { color: '#ef4444', opacity: 0.08 },
        data: props.heap,
      },
      {
        name: '文件句柄', type: 'line' as const, yAxisIndex: 1,
        smooth: true, symbol: 'none',
        lineStyle: { width: 1.6, color: '#f59e0b', type: 'dashed' as const },
        data: props.handles,
      },
    ],
  }
})
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="flex items-center justify-between gap-2 px-1 mb-1">
      <HoverTip
        :tip="'核心问题（稳定性）：长跑期间资源是否单调爬升不回收？\n\n判读：\n· 堆内存锯齿但整体平 → 正常（GC 在回收）\n· 堆内存锯齿且整体上扬 → 疑似内存泄漏\n· 句柄数只增不减 → 连接/文件句柄泄漏\n\n（数据源：被测服务端监控；当前 mock 占位）'"
        :is-dark="isDark"
      >
        <span class="text-[11.5px]" :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }">
          内存 &amp; 句柄泄漏检测
        </span>
      </HoverTip>
      <span v-if="verdict" class="text-[10.5px] tabular-nums" :style="{ color: verdict.color }">
        {{ verdict.text }}
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
