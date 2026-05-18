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
  buildSeriesOption, CONNECT_GROUP, fmtBytesRate, statsOf, type SeriesSpec,
} from './chartFactory'
import { colorFor, widthFor } from './chartColors'
import { SEMANTIC } from './semanticColors'
import HoverTip from './HoverTip.vue'

use([LineChart, GridComponent, TooltipComponent, TitleComponent, LegendComponent, CanvasRenderer])

const props = withDefaults(defineProps<{
  overall: RunMetricsSeries | null
  byTg: Record<string, RunMetricsSeries>
  samplerSelected: Record<string, boolean>
  // 剔除失败样本：有 bytes_recv_ok 数据走 _ok，没有退回 bytes_recv（兼容旧 run）
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

function isVisible(name: string): boolean {
  if (name === 'all') return props.samplerSelected['all'] !== false
  return props.samplerSelected[name] === true
}

// excludeKo=true 时区分两种空：
//   · bytes_recv_ok === undefined → 老后端没 OK 切片 → 退回 bytes_recv（兼容旧 run）
//   · bytes_recv_ok === [] → 新后端但该 sample 100% 失败 → 返回空，曲线消失
function recvFor(series: RunMetricsSeries | null | undefined): SeriesPoint[] {
  if (!series) return []
  if (!props.excludeKo) return series.bytes_recv || []
  if (series.bytes_recv_ok === undefined) return series.bytes_recv || []
  return series.bytes_recv_ok
}

const allSpecs = computed<SeriesSpec[]>(() => {
  const specs: SeriesSpec[] = []
  const allRecv = recvFor(props.overall)
  if (allRecv.length) {
    specs.push({
      name: 'all',
      data: allRecv,
      color: colorFor('all'),
      lineWidth: widthFor('all'),
      area: true,
    })
  }
  for (const tx of txList.value) {
    const series = props.byTg[tx]
    specs.push({
      name: tx,
      data: recvFor(series),
      color: colorFor(tx),
      lineWidth: widthFor(tx),
    })
  }
  return specs
})

// series 数组保持稳定，通过 legend.selected 控可见 → echarts 不重建图
const option = computed(() => {
  const base = buildSeriesOption(
    allSpecs.value,
    props.isDark,
    'B/s',
    { showLegend: false, hideXAxisLabel: props.compact },
  )
  const yAxis = {
    ...(base as any).yAxis,
    axisLabel: {
      ...(base as any).yAxis.axisLabel,
      formatter: (v: number) => fmtBytesRate(v),
    },
  }
  const selected: Record<string, boolean> = {}
  for (const s of allSpecs.value) selected[s.name] = isVisible(s.name)
  return {
    ...base,
    yAxis,
    legend: {
      show: false,
      data: allSpecs.value.map((s) => s.name),
      selected,
    },
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
  allSpecs.value.map((s) => {
    const st = statsOf(s.data)
    return { name: s.name, color: s.color, mean: st.mean, max: st.max, visible: isVisible(s.name) }
  }),
)

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
          网络流量（接收） · KB/s{{ excludeKo ? ' · 剔除失败' : '' }}
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
            <tr :style="{ color: SEMANTIC.saturation }">
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
              <td class="py-0.5 px-1 text-right">{{ fmtKiB(row.mean) }}</td>
              <td class="py-0.5 pl-1 text-right">{{ fmtKiB(row.max) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
