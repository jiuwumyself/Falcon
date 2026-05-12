<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import VChart from 'vue-echarts'
import { use, connect } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, TitleComponent, LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { LatencyBreakdownResponse, RunMetricsSeries } from '@/types/task'
import { runsApi } from '@/lib/api'
import {
  buildSeriesOption, CONNECT_GROUP, statsOf, type SeriesSpec,
} from './chartFactory'
import { colorFor, widthFor, pickDefaultSelected } from './chartColors'
import { LATENCY_BREAKDOWN, SEMANTIC } from './semanticColors'

use([LineChart, GridComponent, TooltipComponent, TitleComponent, LegendComponent, CanvasRenderer])

const props = withDefaults(defineProps<{
  overall: RunMetricsSeries | null
  byTg: Record<string, RunMetricsSeries>
  runId: string | null
  isDark: boolean
  /** small multiples 紧贴布局：隐藏 x 轴标签让最底下一张图承担 */
  compact?: boolean
}>(), { compact: false })

const chartRef = ref<any>(null)
type Mode = 'all-percentiles' | 'tx-p95' | 'breakdown'
const mode = ref<Mode>('all-percentiles')
// P0 #2：'剔除失败样本'toggle。仅 all-percentiles 模式有效，切到 p50/95/99_ok_ms 数据。
// 默认 false 保留含 KO 的旧行为做 backward compat；用户切到 true 才看真实业务延迟。
const excludeKO = ref(false)

// 拆解数据按需 fetch（不进 5s metrics 轮询，避免每 5s 扫一次 JTL 拖累）
const breakdown = ref<LatencyBreakdownResponse | null>(null)
const breakdownLoading = ref(false)
// 缓存对应的 (runId, excludeKO)，任一变化都失效
const breakdownCacheKey = ref<string | null>(null)

async function fetchBreakdown() {
  const id = props.runId
  if (!id) return
  if (breakdownLoading.value) return
  breakdownLoading.value = true
  try {
    breakdown.value = await runsApi.latencyBreakdown(id, excludeKO.value)
    breakdownCacheKey.value = `${id}:${excludeKO.value}`
  } catch {
    // 静默失败：JTL 不存在 / 后端 500，保持 breakdown=null
  } finally {
    breakdownLoading.value = false
  }
}

// 切到 breakdown 且数据未加载、run 切换、或 excludeKO toggle → fetch
watch(
  [() => mode.value, () => props.runId, excludeKO],
  ([m, id, ex]) => {
    if (m !== 'breakdown') return
    if (!id) return
    const key = `${id}:${ex}`
    if (breakdownCacheKey.value !== key) {
      breakdown.value = null
      void fetchBreakdown()
    }
  },
  { immediate: true },
)

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
    // P0 #2：excludeKO=true 时切到 OK 单独的分位数（剔除 KO 样本，看真实业务延迟）
    if (excludeKO.value) {
      return [
        { name: 'P50 (OK)', data: props.overall.p50_ok_ms || [], color: SEMANTIC.success, lineWidth: 2, area: true },
        { name: 'P95 (OK)', data: props.overall.p95_ok_ms || [], color: SEMANTIC.latency, lineWidth: 2 },
        { name: 'P99 (OK)', data: props.overall.p99_ok_ms || [], color: SEMANTIC.errors, lineWidth: 2 },
      ]
    }
    return [
      { name: 'P50', data: props.overall.p50_ms, color: SEMANTIC.success, lineWidth: 2, area: true },
      { name: 'P95', data: props.overall.p95_ms, color: SEMANTIC.latency, lineWidth: 2 },
      { name: 'P99', data: props.overall.p99_ms, color: SEMANTIC.errors, lineWidth: 2 },
    ]
  }
  if (mode.value === 'breakdown') {
    const b = breakdown.value
    if (!b) return []
    // 三段堆叠面积 = Connect + Server + Receive；总高 = elapsed
    // 颜色对应常见瓶颈源：网络（蓝）/ 服务端（红）/ 数据传输（黄）
    // solidArea + 边界线：堆叠模式必须实色填充 + 描边，渐变 fade-out 会让三条
    // 接触点重叠成糊状（用户实测看不清）。alpha 0.55 实色 + 1.5px 边界线最清晰。
    return [
      { name: 'Connect (网络握手)', data: b.connect_ms, color: LATENCY_BREAKDOWN.connect, lineWidth: 1.5, area: true, solidArea: true, stack: 'lat' },
      { name: 'Server (服务端处理)', data: b.server_ms, color: LATENCY_BREAKDOWN.server, lineWidth: 1.5, area: true, solidArea: true, stack: 'lat' },
      { name: 'Receive (数据接收)', data: b.receive_ms, color: LATENCY_BREAKDOWN.receive, lineWidth: 1.5, area: true, solidArea: true, stack: 'lat' },
    ]
  }
  // tx-p95 模式。excludeKO=true 时切到 *_ok_ms 系列（仅 success=true 样本）
  const specs: SeriesSpec[] = []
  const allP95 = excludeKO.value
    ? (props.overall?.p95_ok_ms || [])
    : (props.overall?.p95_ms || [])
  if (allP95.length) {
    specs.push({
      name: 'all',
      data: allP95,
      color: colorFor('all'),
      lineWidth: widthFor('all'),
      area: true,
    })
  }
  for (const tx of txList.value) {
    const series = props.byTg[tx]
    const data = excludeKO.value
      ? (series?.p95_ok_ms || [])
      : (series?.p95_ms || [])
    specs.push({
      name: tx,
      data,
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
    { showLegend: true, hideXAxisLabel: props.compact },
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
    <div class="flex items-center justify-between mb-1.5">
      <div class="flex items-center gap-3">
        <div class="flex items-center gap-1.5">
          <span class="w-0.5 h-3.5 rounded-full" :style="{ background: SEMANTIC.latency }" />
          <span class="text-[11.5px]"
                :style="{ color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.65)' }">
            延迟 · ms
          </span>
        </div>
        <!-- 剔除失败样本 toggle：三种 mode 全支持
             - 总览 P50/P95/P99 → 切到 p50/95/99_ok_ms
             - 按接口 P95 → 切到 by_tg 的 p95_ok_ms
             - 拆解三段 → latency-breakdown 端点带 exclude_ko=true 重拉 -->
        <label
          class="flex items-center gap-1 text-[11px] cursor-pointer"
          :title="'勾选后曲线切到 OK 样本单独的分位数（剔除 401/403 等失败拉低真实延迟分布）'"
          :style="{ color: isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.6)' }"
        >
          <input type="checkbox" v-model="excludeKO" class="cursor-pointer" />
          剔除失败样本
        </label>
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
          P50/P95/P99
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
        <button
          type="button"
          class="px-2.5 py-0.5 rounded transition-colors cursor-pointer"
          title="按秒拆 Connect / 服务端处理 / 数据接收 三段堆叠，看 RT 高在哪一段"
          :style="{
            background: mode === 'breakdown'
              ? (isDark ? 'rgba(255,255,255,0.10)' : 'rgba(255,255,255,0.95)')
              : 'transparent',
            color: mode === 'breakdown'
              ? (isDark ? 'rgba(255,255,255,0.92)' : 'rgba(0,0,0,0.85)')
              : (isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)'),
            boxShadow: mode === 'breakdown'
              ? (isDark ? 'none' : '0 1px 2px rgba(0,0,0,0.06)')
              : 'none',
          }"
          @click="mode = 'breakdown'"
        >
          拆解三段
        </button>
      </div>
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
