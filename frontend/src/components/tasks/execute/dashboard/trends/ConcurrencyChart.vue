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

use([LineChart, GridComponent, TooltipComponent, TitleComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  data: SeriesPoint[]
  isDark: boolean
}>()

const chartRef = ref<any>(null)

const option = computed(() =>
  buildSeriesOption(
    [
      {
        name: 'Threads',
        data: props.data,
        color: '#a855f7',
        lineWidth: 1.6,
        area: true,
        formatter: (v: number) => `${Math.round(v)}`,
      },
    ],
    props.isDark,
    'VU',
    { showLegend: false, gridBottom: 24 },
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
      <div
        class="text-[11.5px]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }"
      >
        并发数
      </div>
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
