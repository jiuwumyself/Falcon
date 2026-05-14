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
  buildSeriesOption, CONNECT_GROUP, fmtBytesRate, statsOf, type SeriesSpec,
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

const initialized = ref(false)
const legendSelected = ref<Record<string, boolean>>({})

watch(
  txList,
  (txs) => {
    if (initialized.value) return
    if (!txs.length && !props.overall?.bytes_recv.length) return
    const recvByTx: Record<string, number> = {}
    for (const tx of txs) {
      recvByTx[tx] = statsOf(props.byTg[tx]?.bytes_recv || []).mean
    }
    legendSelected.value = pickDefaultSelected(txs, recvByTx, 5)
    initialized.value = true
  },
  { immediate: true },
)

const seriesSpecs = computed<SeriesSpec[]>(() => {
  // 按"接收字节"做主线（参考 Grafana 模板）。表里同时显示 Mean / Max。
  const specs: SeriesSpec[] = []
  if (props.overall?.bytes_recv.length) {
    specs.push({
      name: 'all',
      data: props.overall.bytes_recv,
      color: colorFor('all'),
      lineWidth: widthFor('all'),
      area: true,
    })
  }
  for (const tx of txList.value) {
    const series = props.byTg[tx]
    specs.push({
      name: tx,
      data: series?.bytes_recv || [],
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
    'B/s',
    { showLegend: true, hideXAxisLabel: props.compact },
  )
  // Y 轴格式化成 KiB/MiB
  const yAxis = {
    ...(base as any).yAxis,
    axisLabel: {
      ...(base as any).yAxis.axisLabel,
      formatter: (v: number) => fmtBytesRate(v),
    },
  }
  return {
    ...base,
    yAxis,
    legend: {
      ...base.legend,
      selected: legendSelected.value,
      type: 'scroll' as const,
    },
    series: base.series.map((s: any) => ({
      ...s,
      // tooltip 格式化也走 fmtBytesRate
    })),
    tooltip: {
      ...base.tooltip,
      formatter: (params: any) => {
        const arr = Array.isArray(params) ? params : [params]
        if (!arr.length) return ''
        const ts = new Date(arr[0].value[0])
        const tsStr = ts.toLocaleTimeString('zh-CN', { hour12: false })
        const lines = arr
          .filter((p: any) => p.value && p.value[1] != null)
          .sort((a: any, b: any) => b.value[1] - a.value[1])
          .map(
            (p: any) =>
              `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color};margin-right:6px"></span>${p.seriesName}: <b>${fmtBytesRate(p.value[1])}</b>`,
          )
        return `<div style="font-size:10.5px;color:${props.isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)'};margin-bottom:4px">${tsStr}</div>${lines.join('<br/>')}`
      },
    },
  }
})

const tableRows = computed(() =>
  seriesSpecs.value.map((s) => {
    const st = statsOf(s.data)
    return { name: s.name, color: s.color, mean: st.mean, max: st.max }
  }),
)

function toggleSeries(name: string) {
  legendSelected.value = {
    ...legendSelected.value,
    [name]: !legendSelected.value[name],
  }
}

// 表格单元只显示 KiB/s 数值（不带单位），统一行间标度——单位由 header "KB/s" 标注。
// Y 轴 / tooltip 继续走 fmtBytesRate 自动换算（MiB/s · KiB/s）。
function fmtKiB(bps: number): string {
  const kib = bps / 1024
  if (kib < 10) return kib.toFixed(2)
  if (kib < 100) return kib.toFixed(1)
  return kib.toFixed(0)
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
    <!-- 左侧 ribbon 标识：紫色 saturation 类（流量/吞吐资源占用语义），与 RPS/延迟 ribbon 对齐 -->
    <div class="flex items-center gap-1.5 mb-1.5">
      <span class="w-0.5 h-3.5 rounded-full" :style="{ background: SEMANTIC.saturation }" />
      <HoverTip
        :tip="'核心问题：是不是被网卡 / 带宽限住了？\n\n判读条件：\n· 大多数业务场景这张图跟 RPS 同形（信噪比低）\n· stress 场景下「系统挂前网卡被打满」才有诊断价值\n· 字节数远高于 RPS × 平均响应体大小 → 可能附件 / 大返回包\n· 接收高但 RPS 低 → 单请求返回包巨大，看接口设计'"
        :is-dark="isDark"
      >
        <span class="text-[11.5px]"
              :style="{ color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.65)' }">
          网络流量（接收） · KB/s
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
              <td class="py-0.5 px-1 text-right">{{ fmtKiB(row.mean) }}</td>
              <td class="py-0.5 pl-1 text-right">{{ fmtKiB(row.max) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
