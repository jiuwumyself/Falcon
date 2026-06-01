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
  // 实测并发(JTL allThreads/grpThreads 每秒峰值)，画实线。空 = 还没拉到/运行早期
  data: SeriesPoint[]
  // 计划并发(plannedCurve 按配置算)，画虚线当参照
  plannedData?: SeriesPoint[]
  xRange?: [number, number] | null
  isDark: boolean
}>()

const chartRef = ref<any>(null)

const hasReal = computed(() => props.data.length > 0)

const option = computed(() => {
  const specs = []
  // 计划虚线(参照基准)：始终画，无填充、muted
  if (props.plannedData && props.plannedData.length) {
    specs.push({
      name: '计划',
      data: props.plannedData,
      color: props.isDark ? 'rgba(148,163,184,0.7)' : 'rgba(100,116,139,0.7)',
      lineWidth: 1.4,
      smooth: false,
      dashed: true,
      formatter: (v: number) => `${Math.round(v)}`,
    })
  }
  // 实测实线：有数据才画。VU 离散 + 线性 ramp，关 smooth 保峰值真实
  if (hasReal.value) {
    specs.push({
      name: '实测',
      data: props.data,
      color: SEMANTIC.saturation,
      lineWidth: 1.8,
      area: true,
      smooth: false,
      formatter: (v: number) => `${Math.round(v)}`,
    })
  }
  return buildSeriesOption(
    specs,
    props.isDark,
    'VU',
    { showLegend: specs.length > 1, gridBottom: 24, xRange: props.xRange ?? null },
  )
})

// 当前/峰值统计：优先实测，没拉到则用计划
const statSource = computed(() =>
  hasReal.value ? props.data : (props.plannedData ?? []),
)
const current = computed(() => {
  const arr = statSource.value
  if (!arr.length) return 0
  return arr[arr.length - 1][1]
})
const peak = computed(() => statsOf(statSource.value).max)

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
        :tip="'核心问题：JMeter 实际打出的并发(实线)有没有跟上计划(虚线)？\n\n判读条件：\n· 实测(实线)来自 JTL 的 allThreads/grpThreads 每秒峰值——真实活跃线程数\n· 计划(虚线)按线程组配置算的目标曲线，全程当参照基准\n· 实测 < 计划 → 压力机线程起不来 / 系统拖慢到要堆线程(ArrivalsTG)\n· baseline/soak 应该是水平直线、load/stress 阶梯爬升、spike 单峰\n· 运行早期实测还在从 JTL 长出来，只见计划虚线属正常'"
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
        {{ hasReal ? '实测' : '计划' }} 当前 {{ Math.round(current) }} · 峰值 {{ Math.round(peak) }}
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
