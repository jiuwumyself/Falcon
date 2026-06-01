<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { SamplerStat } from '@/types/task'
import { axisColor, gridLineColor, labelColor, tooltipBg } from './chartFactory'
import { colorFor, withAlpha } from './chartColors'
import HoverTip from './HoverTip.vue'

use([ScatterChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

// throughput 场景 图②：按接口的「吞吐-延迟」气泡图。
// x=该接口 TPS / y=均值延迟 / 气泡大小=延迟方差(p99-p50)。一眼看出「哪个接口是
// 吞吐瓶颈、哪个接口尾延迟抖得厉害」。数据来自 SamplerStat（可接真）。
const props = defineProps<{
  stats: SamplerStat[]
  isDark: boolean
}>()

// 气泡半径：方差(p99-p50)开方映射到 [10, 40]
function bubbleSize(s: SamplerStat): number {
  const variance = Math.max(0, s.p99_ms - s.p50_ms)
  return Math.min(40, Math.max(10, Math.sqrt(variance) * 1.8))
}

// 「按接口」图：剔除 'all' 聚合行——它的 TPS 是各接口之和，会把 x 轴撑歪、把真实
// 接口挤成一坨；聚合值另有 KPI 条 / RPS 图表达，这里只比接口。
const rows = computed(() => props.stats.filter((s) => s.label !== 'all'))

const series = computed(() =>
  rows.value.map((s) => {
    const hue = colorFor(s.label)
    return {
      name: s.label,
      type: 'scatter' as const,
      symbolSize: bubbleSize(s),
      itemStyle: { color: withAlpha(hue, 0.45), borderColor: hue, borderWidth: 1.4 },
      data: [{ value: [s.avg_rps, s.avg_ms], stat: s }],
    }
  }),
)

const hasData = computed(() => rows.value.length > 0)

const option = computed(() => ({
  grid: { left: 50, right: 18, top: 30, bottom: 32 },
  legend: {
    top: 0, left: 'center', itemWidth: 9, itemHeight: 9, itemGap: 10,
    textStyle: { color: labelColor(props.isDark), fontSize: 10 },
  },
  tooltip: {
    trigger: 'item' as const,
    formatter: (p: any) => {
      const s: SamplerStat = p.data.stat
      const f = (v: number) => Number(v).toFixed(2)
      return `${p.seriesName}<br/>TPS ${f(s.avg_rps)} · 均值 ${f(s.avg_ms)}ms<br/>P50 ${f(s.p50_ms)} · P99 ${f(s.p99_ms)}ms`
    },
    ...tooltipBg(props.isDark),
  },
  xAxis: {
    type: 'value' as const,
    name: 'TPS',
    nameLocation: 'middle' as const,
    nameGap: 22,
    min: 0,
    nameTextStyle: { color: labelColor(props.isDark), fontSize: 10 },
    axisLine: { lineStyle: { color: axisColor(props.isDark) } },
    axisLabel: { color: labelColor(props.isDark), fontSize: 10 },
    splitLine: { lineStyle: { color: gridLineColor(props.isDark) } },
  },
  yAxis: {
    type: 'value' as const,
    name: '均值延迟 ms',
    nameLocation: 'middle' as const,
    nameGap: 36,
    min: 0,
    nameTextStyle: { color: labelColor(props.isDark), fontSize: 10 },
    axisLine: { show: false },
    axisLabel: { color: labelColor(props.isDark), fontSize: 10 },
    splitLine: { lineStyle: { color: gridLineColor(props.isDark) } },
  },
  series: series.value,
}))
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="flex items-center px-1 mb-1">
      <HoverTip
        :tip="'核心问题（吞吐量）：哪个接口是吞吐瓶颈 / 尾延迟抖得最厉害？\n\n判读：\n· 气泡靠右下（高 TPS 低延迟）→ 健康\n· 气泡靠左上（低 TPS 高延迟）→ 拖后腿的瓶颈接口\n· 气泡越大 → 该接口 P99-P50 跨度越大，延迟越不稳定'"
        :is-dark="isDark"
      >
        <span class="text-[11.5px]" :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }">
          吞吐 vs 延迟 气泡图（按接口）
        </span>
      </HoverTip>
    </div>
    <div class="flex-1 min-h-0">
      <VChart v-if="hasData" :option="option" autoresize style="width: 100%; height: 100%" />
      <div
        v-else
        class="h-full flex items-center justify-center text-[11px]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)' }"
      >暂无接口数据</div>
    </div>
  </div>
</template>
