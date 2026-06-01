<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { SamplerStat } from '@/types/task'
import { axisColor, gridLineColor, labelColor, tooltipBg } from './chartFactory'
import { colorFor, withAlpha } from './chartColors'

use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

// 各接口响应时间分布：每接口 min / 均值 / max 三组横条对比。
// 数据来自 SamplerStat（含 'all' 行）。排序：'all' 置顶，其余按均值(avg_ms)升序。
// 配色：每个接口用自己的稳定色(colorFor，'all' 为绿)，min/均值/max 用该色的不同
// 透明度区分（均值最实 78%、min 22%、max 最淡 14%）。
const props = defineProps<{
  stats: SamplerStat[]
  isDark: boolean
}>()

const ALL_LABEL = 'all'

const rows = computed(() => {
  const all = props.stats.filter((s) => s.label === ALL_LABEL)
  const rest = props.stats
    .filter((s) => s.label !== ALL_LABEL)
    .sort((a, b) => a.avg_ms - b.avg_ms)
  return [...all, ...rest]
})

const chartHeight = computed(() => Math.max(150, rows.value.length * 34 + 44))

// 每个 series 的透明度（fill / border）+ 边宽，套在每个接口自己的 hue 上
const ALPHA = {
  min: { fill: 0.22, border: 0.5, bw: 1 },
  avg: { fill: 0.78, border: 1.0, bw: 1.5 },
  max: { fill: 0.14, border: 0.42, bw: 1 },
}

function seriesData(metric: 'min' | 'avg' | 'max') {
  const key = metric === 'min' ? 'min_ms' : metric === 'avg' ? 'avg_ms' : 'max_ms'
  const a = ALPHA[metric]
  // category 默认从下往上 → 数据倒序让 'all' 落在最顶
  return [...rows.value].reverse().map((s) => {
    const hue = colorFor(s.label)
    return {
      value: Math.round(s[key]),
      itemStyle: {
        color: withAlpha(hue, a.fill),
        borderColor: a.border >= 1 ? hue : withAlpha(hue, a.border),
        borderWidth: a.bw,
        borderRadius: 2,
      },
    }
  })
}

// 图例 swatch：中性绿的三档透明度（传达"实=均值"的编码，bar 实际用各接口 hue）
function legendColor(metric: 'min' | 'avg' | 'max') {
  return withAlpha('#10b981', ALPHA[metric].fill)
}

const option = computed(() => {
  const cats = rows.value.map((s) => (s.label === ALL_LABEL ? '全部' : s.label))
  return {
    grid: { left: 8, right: 40, top: 28, bottom: 24, containLabel: true },
    legend: {
      data: [
        { name: 'min', itemStyle: { color: legendColor('min') } },
        { name: '均值', itemStyle: { color: legendColor('avg') } },
        { name: 'max', itemStyle: { color: legendColor('max') } },
      ],
      top: 0,
      right: 0,
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 12,
      textStyle: { color: labelColor(props.isDark), fontSize: 10 },
    },
    tooltip: {
      trigger: 'axis' as const,
      axisPointer: { type: 'shadow' as const },
      valueFormatter: (v: any) => `${Math.round(v)} ms`,
      ...tooltipBg(props.isDark),
    },
    xAxis: {
      type: 'value' as const,
      name: 'ms',
      nameTextStyle: { color: labelColor(props.isDark), fontSize: 10 },
      axisLabel: { color: labelColor(props.isDark), fontSize: 10 },
      axisLine: { lineStyle: { color: axisColor(props.isDark) } },
      splitLine: { lineStyle: { color: gridLineColor(props.isDark) } },
    },
    yAxis: {
      type: 'category' as const,
      data: [...cats].reverse(),
      axisLabel: { color: labelColor(props.isDark), fontSize: 10.5, width: 110, overflow: 'truncate' as const },
      axisLine: { lineStyle: { color: axisColor(props.isDark) } },
      axisTick: { show: false },
    },
    series: [
      { name: 'min', type: 'bar' as const, barGap: '20%', barCategoryGap: '42%', data: seriesData('min') },
      { name: '均值', type: 'bar' as const, data: seriesData('avg') },
      { name: 'max', type: 'bar' as const, data: seriesData('max') },
    ],
  }
})
</script>

<template>
  <div class="flex flex-col">
    <div
      class="text-[12px] font-medium mb-2"
      :style="{ color: isDark ? 'rgba(255,255,255,0.75)' : 'rgba(0,0,0,0.7)' }"
    >
      各接口响应时间分布
      <span class="text-[11px] font-normal" :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }">
        · min / 均值 / max（ms）
      </span>
    </div>
    <VChart v-if="rows.length" :option="option" autoresize :style="{ height: chartHeight + 'px' }" />
  </div>
</template>
