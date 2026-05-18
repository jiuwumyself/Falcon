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
import { colorFor, widthFor } from './chartColors'
import { LATENCY_BREAKDOWN, SEMANTIC } from './semanticColors'
import HoverTip from './HoverTip.vue'

use([LineChart, GridComponent, TooltipComponent, TitleComponent, LegendComponent, CanvasRenderer])

const props = withDefaults(defineProps<{
  overall: RunMetricsSeries | null
  byTg: Record<string, RunMetricsSeries>
  samplerSelected: Record<string, boolean>
  excludeKo: boolean
  runId: string | null
  isDark: boolean
  /** small multiples 紧贴布局：隐藏 x 轴标签让最底下一张图承担 */
  compact?: boolean
}>(), { compact: false })

const emit = defineEmits<{
  (e: 'toggleSampler', name: string): void
}>()

const chartRef = ref<any>(null)
type Mode = 'tx-p95' | 'all-percentiles' | 'breakdown'
// 默认 tx-p95：跟 RPS / Network 都默认按接口切，保持一致
const mode = ref<Mode>('tx-p95')

const breakdown = ref<LatencyBreakdownResponse | null>(null)
const breakdownLoading = ref(false)
const breakdownCacheKey = ref<string | null>(null)

async function fetchBreakdown() {
  const id = props.runId
  if (!id) return
  if (breakdownLoading.value) return
  breakdownLoading.value = true
  try {
    breakdown.value = await runsApi.latencyBreakdown(id, props.excludeKo)
    breakdownCacheKey.value = `${id}:${props.excludeKo}`
  } catch {
    // 静默：保持 breakdown=null
  } finally {
    breakdownLoading.value = false
  }
}

// breakdown 切 excludeKo 时不清旧数据 → 新数据回来才覆盖，避免图清空 → 闪烁。
// 仅当 runId 变了才清（换 run 旧数据不能复用）。
watch(
  [() => mode.value, () => props.runId, () => props.excludeKo],
  ([m, id, ex], [, prevId]) => {
    if (m !== 'breakdown') return
    if (!id) return
    const key = `${id}:${ex}`
    if (breakdownCacheKey.value !== key) {
      if (prevId && id !== prevId) breakdown.value = null
      void fetchBreakdown()
    }
  },
  { immediate: true },
)

const txList = computed(() => Object.keys(props.byTg).sort())

function isVisible(name: string): boolean {
  if (name === 'all') return props.samplerSelected['all'] !== false
  return props.samplerSelected[name] === true
}

// tx-p95 模式：excludeKo=true 时区分两种空：
//   · p95_ok_ms === undefined → 老后端没 OK 切片 → 退回 p95_ms（兼容旧 run）
//   · p95_ok_ms === [] → 新后端但该 sample 100% 失败 → 返回空，曲线消失（"剔除"
//     语义直观，跟 RpsChart 的 rps - error_count 扣到 0 同效果）
function p95For(series: { p95_ms?: any[]; p95_ok_ms?: any[] } | null | undefined): any[] {
  if (!series) return []
  if (!props.excludeKo) return series.p95_ms || []
  if (series.p95_ok_ms === undefined) return series.p95_ms || []
  return series.p95_ok_ms
}
const allSpecsTxP95 = computed<SeriesSpec[]>(() => {
  const specs: SeriesSpec[] = []
  const allP95 = p95For(props.overall)
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
    specs.push({
      name: tx,
      data: p95For(props.byTg[tx]),
      color: colorFor(tx),
      lineWidth: widthFor(tx),
    })
  }
  return specs
})

// 'all-percentiles' / 'breakdown' 模式的固定 3 系列
const fixedSpecs = computed<SeriesSpec[]>(() => {
  if (mode.value === 'all-percentiles') {
    if (!props.overall) return []
    // name 始终 'P50/P95/P99'（id 稳定，echarts smart-merge 不重画 → 切 excludeKo 不闪）
    // 数据按 excludeKo 切换；OK 字段 undefined 时退回原字段（兼容老 run）
    const o = props.overall
    const p50 = props.excludeKo ? (o.p50_ok_ms ?? o.p50_ms) : o.p50_ms
    const p95 = props.excludeKo ? (o.p95_ok_ms ?? o.p95_ms) : o.p95_ms
    const p99 = props.excludeKo ? (o.p99_ok_ms ?? o.p99_ms) : o.p99_ms
    return [
      { name: 'P50', data: p50, color: SEMANTIC.success, lineWidth: 2, area: true },
      { name: 'P95', data: p95, color: SEMANTIC.latency, lineWidth: 2 },
      { name: 'P99', data: p99, color: SEMANTIC.errors, lineWidth: 2 },
    ]
  }
  if (mode.value === 'breakdown') {
    const b = breakdown.value
    if (!b) return []
    return [
      { name: 'Connect (网络握手)', data: b.connect_ms, color: LATENCY_BREAKDOWN.connect, lineWidth: 1.5, area: true, solidArea: true, stack: 'lat' },
      { name: 'Server (服务端处理)', data: b.server_ms, color: LATENCY_BREAKDOWN.server, lineWidth: 1.5, area: true, solidArea: true, stack: 'lat' },
      { name: 'Receive (数据接收)', data: b.receive_ms, color: LATENCY_BREAKDOWN.receive, lineWidth: 1.5, area: true, solidArea: true, stack: 'lat' },
    ]
  }
  // tx-p95：全集 specs，可见性走 legend.selected
  return allSpecsTxP95.value
})

const option = computed(() => {
  const base = buildSeriesOption(
    fixedSpecs.value,
    props.isDark,
    'ms',
    { showLegend: false, hideXAxisLabel: props.compact },
  )
  // 仅 tx-p95 模式用 legend.selected 控可见；其他 mode 全显
  if (mode.value === 'tx-p95') {
    const selected: Record<string, boolean> = {}
    for (const s of fixedSpecs.value) selected[s.name] = isVisible(s.name)
    return {
      ...base,
      legend: {
        show: false,
        data: fixedSpecs.value.map((s) => s.name),
        selected,
      },
    }
  }
  return base
})

// 表格行：tx-p95 用 allSpecsTxP95；其他 mode 用 fixedSpecs（P50/95/99 总览 或 breakdown 三段）
const tableRows = computed(() => {
  const specs = mode.value === 'tx-p95' ? allSpecsTxP95.value : fixedSpecs.value
  return specs.map((s) => {
    const st = statsOf(s.data)
    return {
      name: s.name,
      color: s.color,
      mean: st.mean,
      max: st.max,
      // 仅 tx-p95 模式下表格行支持点击切换；其他 mode 不可点
      clickable: mode.value === 'tx-p95',
      visible: mode.value === 'tx-p95' ? isVisible(s.name) : true,
    }
  })
})

function onRowClick(row: { name: string; clickable: boolean }) {
  if (!row.clickable) return
  emit('toggleSampler', row.name)
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
      <div class="flex items-center gap-1.5">
        <span class="w-0.5 h-3.5 rounded-full" :style="{ background: SEMANTIC.latency }" />
        <HoverTip
          :tip="'核心问题：用户感受到的响应时间是多长？尾延迟有多差？\n\n判读条件：\n· P99 / P50 比 > 3 → 长尾严重，少数请求拖累用户体验\n· P99 缓慢上升 → 内存泄漏 / 连接池 leak（soak 场景重点关注）\n· P99 陡升 → 系统逼近极限（load/stress 拐点信号）\n· 周期性峰 → GC pause / 锁竞争 / 定时任务干扰'"
          :is-dark="isDark"
        >
          <span class="text-[11.5px]"
                :style="{ color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.65)' }">
            延迟 · ms{{ excludeKo ? ' · 剔除失败' : '' }}
          </span>
        </HoverTip>
      </div>
      <!-- Segmented control 排序：按接口 P95（默认）/ P50/P95/P99 / 拆解三段 -->
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
            background: mode === 'tx-p95'
              ? (isDark ? 'rgba(255,255,255,0.10)' : 'rgba(255,255,255,0.95)')
              : 'transparent',
            color: mode === 'tx-p95'
              ? (isDark ? 'rgba(255,255,255,0.92)' : 'rgba(0,0,0,0.85)')
              : (isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)'),
          }"
          @click="mode = 'tx-p95'"
        >按接口 P95</button>
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
          }"
          @click="mode = 'all-percentiles'"
        >P50/P95/P99</button>
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
          }"
          @click="mode = 'breakdown'"
        >拆解三段</button>
      </div>
    </div>
    <div class="flex-1 min-h-0 grid grid-cols-[1fr_220px] gap-3">
      <VChart
        ref="chartRef"
        :option="option"
        :update-options="{ notMerge: false, replaceMerge: ['series'] }"
        autoresize
        style="width: 100%; height: 100%"
      />
      <div class="overflow-y-auto no-scrollbar text-[11px] tabular-nums">
        <table class="w-full">
          <thead>
            <tr :style="{ color: SEMANTIC.latency }">
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
              :class="row.clickable ? 'cursor-pointer' : ''"
              :style="{
                color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.8)',
                opacity: row.visible ? 1 : 0.35,
              }"
              @click="onRowClick(row)"
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
