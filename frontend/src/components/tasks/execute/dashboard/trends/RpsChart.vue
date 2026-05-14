<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import VChart from 'vue-echarts'
import { use, connect } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, TitleComponent, LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { RunMetricsSeries } from '@/types/task'
import {
  buildSeriesOption, CONNECT_GROUP, statsOf, type SeriesSpec,
} from './chartFactory'
import { colorFor, widthFor, pickDefaultSelected } from './chartColors'
import { SEMANTIC } from './semanticColors'
import HoverTip from './HoverTip.vue'

use([LineChart, GridComponent, TooltipComponent, TitleComponent, LegendComponent, CanvasRenderer])

const props = withDefaults(defineProps<{
  overall: RunMetricsSeries | null
  byTg: Record<string, RunMetricsSeries>
  isDark: boolean
  /** small multiples 紧贴布局：隐藏 x 轴标签让最底下一张图承担 */
  compact?: boolean
}>(), { compact: false })

const chartRef = ref<any>(null)

const txList = computed(() => Object.keys(props.byTg).sort())

// 默认选中：all + RPS top 5 transaction（首屏不糊）
const initialized = ref(false)
const legendSelected = ref<Record<string, boolean>>({})

watch(
  txList,
  (txs) => {
    if (initialized.value) return
    if (!txs.length && !props.overall?.rps.length) return
    const rpsByTx: Record<string, number> = {}
    for (const tx of txs) {
      rpsByTx[tx] = statsOf(props.byTg[tx]?.rps || []).mean
    }
    legendSelected.value = pickDefaultSelected(txs, rpsByTx, 5)
    initialized.value = true
  },
  { immediate: true },
)

const seriesSpecs = computed<SeriesSpec[]>(() => {
  const specs: SeriesSpec[] = []
  if (props.overall?.rps.length) {
    specs.push({
      name: 'all',
      data: props.overall.rps,
      color: colorFor('all'),
      lineWidth: widthFor('all'),
      area: true,
    })
  }
  for (const tx of txList.value) {
    const series = props.byTg[tx]
    specs.push({
      name: tx,
      data: series?.rps || [],
      color: colorFor(tx),
      lineWidth: widthFor(tx),
    })
  }
  return specs
})

const option = computed(() => {
  const base = buildSeriesOption(
    seriesSpecs.value,
    props.isDark,
    'req/s',
    { showLegend: true, hideXAxisLabel: props.compact },
  )
  return {
    ...base,
    legend: {
      ...base.legend,
      selected: legendSelected.value,
      type: 'scroll' as const,
    },
  }
})

const tableRows = computed(() =>
  seriesSpecs.value.map((s) => {
    const st = statsOf(s.data)
    return { name: s.name, color: s.color, ...st }
  }),
)

function toggleSeries(name: string) {
  legendSelected.value = {
    ...legendSelected.value,
    [name]: !legendSelected.value[name],
  }
}

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
  <div class="flex flex-col h-full min-h-0">
    <!-- 左侧 ribbon 标识替代居中标题：去 chartjunk + 节省纵向空间 -->
    <div class="flex items-center gap-1.5 mb-1.5">
      <span class="w-0.5 h-3.5 rounded-full" :style="{ background: SEMANTIC.traffic }" />
      <HoverTip
        :tip="'核心问题：系统的真实吞吐能力是多少？\n\n判读条件：\n· 线性增长 → 系统未饱和\n· 平台期（横线）→ 已到瓶颈，加 VU 不再涨\n· 下降 → 崩溃前兆 / 错误吞掉成功请求\n· 周期性抖动 → 可能 GC 撞 / 后端节流'"
        :is-dark="isDark"
      >
        <span class="text-[11.5px]"
              :style="{ color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.65)' }">
          RPS · req/s
        </span>
      </HoverTip>
    </div>
    <div class="flex-1 min-h-0 grid grid-cols-[1fr_220px] gap-3">
      <VChart
        ref="chartRef"
        :option="option"
        autoresize
        style="width: 100%; height: 100%"
      />
      <div class="overflow-y-auto no-scrollbar text-[11px] tabular-nums">
        <table class="w-full">
          <thead>
            <tr :style="{ color: '#3b82f6' }">
              <th class="text-left font-medium pb-1.5"></th>
              <th class="text-right font-medium pb-1.5 px-1">Mean</th>
              <th class="text-right font-medium pb-1.5 pl-1">Max</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in tableRows"
              :key="row.name"
              class="cursor-pointer transition-opacity"
              :style="{
                color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.8)',
                opacity: legendSelected[row.name] === false ? 0.35 : 1,
              }"
              @click="toggleSeries(row.name)"
            >
              <td class="py-0.5 max-w-[110px]">
                <div class="flex items-center gap-1.5 truncate">
                  <span
                    class="inline-block w-2.5 h-0.5"
                    :style="{ background: row.color }"
                  />
                  <span class="truncate" :title="row.name">{{ row.name }}</span>
                </div>
              </td>
              <td class="py-0.5 px-1 text-right">{{ row.mean.toFixed(row.mean < 10 ? 2 : 0) }}</td>
              <td class="py-0.5 pl-1 text-right">{{ row.max.toFixed(row.max < 10 ? 2 : 0) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
