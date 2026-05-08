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

use([LineChart, GridComponent, TooltipComponent, TitleComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  overall: RunMetricsSeries | null
  byTg: Record<string, RunMetricsSeries>
  isDark: boolean
}>()

const chartRef = ref<any>(null)
const mode = ref<'all-percentiles' | 'tx-p95'>('all-percentiles')

const txList = computed(() => Object.keys(props.byTg).sort())

// 模式 2 用：默认勾选 P95 top 5 transaction
const initialized = ref(false)
const legendSelected = ref<Record<string, boolean>>({})

watch(
  [() => mode.value, txList],
  ([m, txs]) => {
    if (m !== 'tx-p95') return
    if (initialized.value) return
    if (!txs.length) return
    const p95ByTx: Record<string, number> = {}
    for (const tx of txs) {
      p95ByTx[tx] = statsOf(props.byTg[tx]?.p95_ms || []).mean
    }
    legendSelected.value = pickDefaultSelected(txs, p95ByTx, 5)
    initialized.value = true
  },
  { immediate: true },
)

const seriesSpecs = computed<SeriesSpec[]>(() => {
  if (mode.value === 'all-percentiles') {
    if (!props.overall) return []
    return [
      { name: 'P50', data: props.overall.p50_ms, color: '#10b981', lineWidth: 2, area: true },
      { name: 'P95', data: props.overall.p95_ms, color: '#f59e0b', lineWidth: 2 },
      { name: 'P99', data: props.overall.p99_ms, color: '#ef4444', lineWidth: 2 },
    ]
  }
  // tx-p95 模式
  const specs: SeriesSpec[] = []
  if (props.overall?.p95_ms.length) {
    specs.push({
      name: 'all',
      data: props.overall.p95_ms,
      color: colorFor('all'),
      lineWidth: widthFor('all'),
      area: true,
    })
  }
  for (const tx of txList.value) {
    const series = props.byTg[tx]
    specs.push({
      name: tx,
      data: series?.p95_ms || [],
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
    'ms',
    { showLegend: true, gridBottom: 30 },
  )
  if (mode.value === 'tx-p95') {
    return {
      ...base,
      legend: {
        ...base.legend,
        selected: legendSelected.value,
        type: 'scroll' as const,
      },
    }
  }
  return base
})

const tableRows = computed(() =>
  seriesSpecs.value.map((s) => {
    const st = statsOf(s.data)
    return { name: s.name, color: s.color, mean: st.mean, max: st.max }
  }),
)

function toggleSeries(name: string) {
  if (mode.value !== 'tx-p95') return
  legendSelected.value = {
    ...legendSelected.value,
    [name]: !legendSelected.value[name],
  }
}

function fmtMs(ms: number): string {
  if (ms < 1000) return `${ms.toFixed(0)} ms`
  return `${(ms / 1000).toFixed(2)} s`
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
    <div class="flex items-center justify-between mb-2">
      <div
        class="flex-1 text-center text-[12px]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.65)' : 'rgba(0,0,0,0.65)' }"
      >
        接口响应时间
      </div>
      <!-- Segmented control 替代原 <select>，提升 mode 切换的发现性 -->
      <div
        class="flex items-center text-[11px] rounded-md p-0.5 gap-0.5"
        :style="{
          background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)',
          border: isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.06)',
        }"
      >
        <button
          type="button"
          class="px-2.5 py-0.5 rounded transition-colors cursor-pointer"
          :style="{
            background: mode === 'all-percentiles'
              ? (isDark ? 'rgba(255,255,255,0.10)' : 'rgba(255,255,255,0.95)')
              : 'transparent',
            color: mode === 'all-percentiles'
              ? (isDark ? 'rgba(255,255,255,0.92)' : 'rgba(0,0,0,0.85)')
              : (isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)'),
            boxShadow: mode === 'all-percentiles'
              ? (isDark ? 'none' : '0 1px 2px rgba(0,0,0,0.06)')
              : 'none',
          }"
          @click="mode = 'all-percentiles'"
        >
          总览 P50/P95/P99
        </button>
        <button
          type="button"
          class="px-2.5 py-0.5 rounded transition-colors cursor-pointer"
          :style="{
            background: mode === 'tx-p95'
              ? (isDark ? 'rgba(255,255,255,0.10)' : 'rgba(255,255,255,0.95)')
              : 'transparent',
            color: mode === 'tx-p95'
              ? (isDark ? 'rgba(255,255,255,0.92)' : 'rgba(0,0,0,0.85)')
              : (isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)'),
            boxShadow: mode === 'tx-p95'
              ? (isDark ? 'none' : '0 1px 2px rgba(0,0,0,0.06)')
              : 'none',
          }"
          @click="mode = 'tx-p95'"
        >
          按接口 P95
        </button>
      </div>
    </div>
    <div class="flex-1 min-h-0 grid grid-cols-[1fr_180px] gap-3">
      <VChart
        ref="chartRef"
        :option="option"
        autoresize
        style="width: 100%; height: 100%; min-height: 220px"
      />
      <div class="overflow-y-auto text-[11px] tabular-nums">
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
              class="transition-opacity"
              :class="mode === 'tx-p95' ? 'cursor-pointer' : ''"
              :style="{
                color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.8)',
                opacity: mode === 'tx-p95' && legendSelected[row.name] === false ? 0.35 : 1,
              }"
              @click="toggleSeries(row.name)"
            >
              <td class="py-0.5 max-w-[100px]">
                <div class="flex items-center gap-1.5 truncate">
                  <span
                    class="inline-block w-2.5 h-0.5"
                    :style="{ background: row.color }"
                  />
                  <span class="truncate" :title="row.name">{{ row.name }}</span>
                </div>
              </td>
              <td class="py-0.5 px-1 text-right">{{ fmtMs(row.mean) }}</td>
              <td class="py-0.5 pl-1 text-right">{{ fmtMs(row.max) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
