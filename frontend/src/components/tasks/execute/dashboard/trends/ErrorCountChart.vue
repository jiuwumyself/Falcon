<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import VChart from 'vue-echarts'
import { use, connect } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, TitleComponent, LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { RunMetricsTotals, SeriesPoint, TaskRun } from '@/types/task'
import {
  buildSeriesOption, CONNECT_GROUP, cumulativeErrorRate,
  lastWindowErrorRate, statsOf,
} from './chartFactory'
import { colorForErrorRate, SEMANTIC } from './semanticColors'

use([LineChart, GridComponent, TooltipComponent, TitleComponent, LegendComponent, CanvasRenderer])

// 总错误图。标题区右侧吃掉了原来的"实时错误率（60s 窗口）"卡片：
// 显示「累计 N.NN% · 60s N.NN% · 峰值 M/s」三段
const props = defineProps<{
  data: SeriesPoint[]
  totals: RunMetricsTotals | null
  run: TaskRun | null
  rpsData: SeriesPoint[]   // 用于算 60s 错误率（同时间窗 errSum / reqSum）
  xRange?: [number, number] | null  // 跨图统一时间窗
  isDark: boolean
}>()

const chartRef = ref<any>(null)

// 按 5s 桶降采样（每桶取 max），跟其他图（RPS/P95 等）的 5s 采样间隔对齐。
// 用 max 而不是 sum/mean：保留 spike 可见性，图上最高点 = 标题"峰值 N/s"严格相等。
function downsample5sMax(data: SeriesPoint[]): SeriesPoint[] {
  if (!data.length) return data
  const buckets = new Map<number, number>()
  for (const [t, v] of data) {
    const key = Math.floor(t / 5000) * 5000
    const cur = buckets.get(key) ?? -Infinity
    if (v > cur) buckets.set(key, v)
  }
  return Array.from(buckets.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([t, v]) => [t, v] as SeriesPoint)
}

const binnedData = computed(() => downsample5sMax(props.data))

const option = computed(() =>
  buildSeriesOption(
    [
      {
        name: '错误数',
        data: binnedData.value,
        color: SEMANTIC.errors,
        lineWidth: 1.6,
        area: true,
        formatter: (v: number) => `${Math.round(v)}`,
      },
    ],
    props.isDark,
    '次/s',
    { showLegend: false, gridBottom: 24, xRange: props.xRange ?? null },
  ),
)

// 峰值用 raw 数据 max（=binnedData max）—— 两者口径相同，图上能找到
const peakRate = computed(() => statsOf(props.data).max)

const cumulativePct = computed(() => cumulativeErrorRate(props.totals))
const recentPct = computed(() =>
  lastWindowErrorRate(props.data, props.rpsData, props.run),
)

onMounted(() => {
  if (chartRef.value && chartRef.value.chart) {
    chartRef.value.chart.group = CONNECT_GROUP
    connect(CONNECT_GROUP)
  }
})
watch(chartRef, (v) => {
  if (v && v.chart) {
    v.chart.group = CONNECT_GROUP
    connect(CONNECT_GROUP)
  }
})
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="flex items-center justify-between gap-2 px-1 mb-1">
      <div
        class="text-[11.5px]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }"
      >
        总错误
      </div>
      <div
        class="text-[10.5px] tabular-nums flex items-center gap-2 flex-wrap justify-end"
        :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
      >
        <span
          v-if="cumulativePct !== null"
          :style="{ color: colorForErrorRate(cumulativePct) }"
          title="累计错误率（fail/req）"
        >累计 {{ cumulativePct.toFixed(2) }}%</span>
        <span
          v-if="recentPct !== null"
          :style="{ color: colorForErrorRate(recentPct) }"
          title="近 60s 滚动窗口错误率"
        >60s {{ recentPct.toFixed(2) }}%</span>
        <span>峰值 {{ Math.round(peakRate) }}/s</span>
      </div>
    </div>
    <div class="flex-1 min-h-0">
      <VChart
        ref="chartRef"
        :option="option"
        autoresize
        style="width: 100%; height: 100%"
      />
    </div>
  </div>
</template>
