<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import VChart from 'vue-echarts'
import { use, connect } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, TitleComponent, LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { SeriesPoint } from '@/types/task'
import { buildSeriesOption, CONNECT_GROUP, statsOf } from './chartFactory'
import { SEMANTIC } from './semanticColors'
import HoverTip from './HoverTip.vue'

use([LineChart, GridComponent, TooltipComponent, TitleComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  data: SeriesPoint[]
  xRange?: [number, number] | null
  isDark: boolean
}>()

const chartRef = ref<any>(null)

const option = computed(() =>
  buildSeriesOption(
    [
      {
        name: 'Threads',
        data: props.data,
        color: SEMANTIC.saturation,
        lineWidth: 1.6,
        area: true,
        formatter: (v: number) => `${Math.round(v)}`,
      },
    ],
    props.isDark,
    'VU',
    { showLegend: false, gridBottom: 24, xRange: props.xRange ?? null },
  ),
)

const current = computed(() => {
  const arr = props.data
  if (!arr.length) return 0
  return arr[arr.length - 1][1]
})

const peak = computed(() => statsOf(props.data).max)

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
    <div class="flex items-center justify-between px-1 mb-1">
      <HoverTip
        :tip="'核心问题：当前实际有多少 VU 在打？ramp 过程平不平？\n\n判读条件：\n· 单 TG 显示实测 active_users；多 TG 切到具体 TG 时显示计划曲线（兜底）\n· baseline/soak 应该是水平直线（恒定 VU）\n· load/stress 应该是阶梯爬升（看每阶 hold 时段是否平直）\n· spike 应该是单峰（5s 起冲 → hold → 5s 退）\n· throughput 由 JMeter 自适应，看系统响应越慢用得 VU 越多'"
        :is-dark="isDark"
      >
        <span class="text-[11.5px]"
              :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }">
          并发数
        </span>
      </HoverTip>
      <div
        class="text-[10.5px] tabular-nums"
        :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
      >
        当前 {{ Math.round(current) }} · 峰值 {{ Math.round(peak) }}
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
