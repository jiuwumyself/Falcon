<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import VChart from 'vue-echarts'
import { use, connect } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, TitleComponent, LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { RunMetricsSeries, SeriesPoint } from '@/types/task'
import {
  buildSeriesOption, CONNECT_GROUP, statsOf, type SeriesSpec,
} from './chartFactory'
import { colorFor, widthFor } from './chartColors'
import { SEMANTIC } from './semanticColors'
import HoverTip from './HoverTip.vue'

use([LineChart, GridComponent, TooltipComponent, TitleComponent, LegendComponent, CanvasRenderer])

const props = withDefaults(defineProps<{
  overall: RunMetricsSeries | null
  byTg: Record<string, RunMetricsSeries>
  // 父组件共享 samplerSelected：visible=true 渲染该 series，其余隐藏（echarts legend.selected 接管）
  samplerSelected: Record<string, boolean>
  // 剔除失败样本：'all' 用精确 rps-error_count；per-sampler error_count 为空时
  // 走 overall.error_rate 比例近似（rps * (1 - rate/100)）
  excludeKo: boolean
  isDark: boolean
  /** small multiples 紧贴布局：隐藏 x 轴标签让最底下一张图承担 */
  compact?: boolean
}>(), { compact: false })

const emit = defineEmits<{
  (e: 'toggleSampler', name: string): void
}>()

const chartRef = ref<any>(null)

const txList = computed(() => Object.keys(props.byTg).sort())

/** rps - error_count 对齐扣减；同 1s 时间戳 map 查找 */
function subtractErrors(rps: SeriesPoint[], errs: SeriesPoint[]): SeriesPoint[] {
  if (!errs?.length) return rps
  const errMap = new Map<number, number>()
  for (const [t, v] of errs) errMap.set(t, v)
  return rps.map(([t, v]) => [t, Math.max(0, v - (errMap.get(t) || 0))] as SeriesPoint)
}

/** 比例近似：rps * (1 - error_rate/100)，error_rate 来自 overall */
function scaleByErrorRate(rps: SeriesPoint[], errRate: SeriesPoint[]): SeriesPoint[] {
  if (!errRate?.length) return rps
  const rateMap = new Map<number, number>()
  for (const [t, v] of errRate) rateMap.set(t, v)
  return rps.map(([t, v]) => [t, Math.max(0, v * (1 - (rateMap.get(t) || 0) / 100))] as SeriesPoint)
}

function rpsFor(series: RunMetricsSeries | null | undefined): SeriesPoint[] {
  if (!series) return []
  if (!props.excludeKo) return series.rps || []
  // 该序列自带 error_count → 精确扣减
  if (series.error_count?.length) {
    return subtractErrors(series.rps || [], series.error_count)
  }
  // 退到 overall.error_rate 按比例近似（per-sampler 后端不拆 OK/KO）
  return scaleByErrorRate(series.rps || [], props.overall?.error_rate || [])
}

function isVisible(name: string): boolean {
  if (name === 'all') return props.samplerSelected['all'] !== false
  return props.samplerSelected[name] === true
}

const allSpecs = computed<SeriesSpec[]>(() => {
  const specs: SeriesSpec[] = []
  const allRps = rpsFor(props.overall)
  if (allRps.length) {
    specs.push({
      name: 'all',
      data: allRps,
      color: colorFor('all'),
      lineWidth: widthFor('all'),
      area: true,
    })
  }
  for (const tx of txList.value) {
    const series = props.byTg[tx]
    specs.push({
      name: tx,
      data: rpsFor(series),
      color: colorFor(tx),
      lineWidth: widthFor(tx),
    })
  }
  return specs
})

// option：series 全集稳定（不增不减），通过 legend.selected 控制可见性 →
// echarts 不重建图，只切换 series 显隐，避免点击 sampler 时整图重画
const option = computed(() => {
  const base = buildSeriesOption(
    allSpecs.value,
    props.isDark,
    'req/s',
    { showLegend: false, hideXAxisLabel: props.compact },
  )
  const selected: Record<string, boolean> = {}
  for (const s of allSpecs.value) selected[s.name] = isVisible(s.name)
  return {
    ...base,
    legend: {
      show: false,
      data: allSpecs.value.map((s) => s.name),
      selected,
    },
  }
})

const tableRows = computed(() =>
  allSpecs.value.map((s) => {
    const st = statsOf(s.data)
    return { name: s.name, color: s.color, mean: st.mean, max: st.max, visible: isVisible(s.name) }
  }),
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
          RPS · req/s{{ excludeKo ? ' · 剔除失败' : '' }}
        </span>
      </HoverTip>
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
                opacity: row.visible ? 1 : 0.35,
              }"
              @click="emit('toggleSampler', row.name)"
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
