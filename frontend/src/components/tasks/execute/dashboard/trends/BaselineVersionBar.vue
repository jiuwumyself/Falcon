<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { axisColor, gridLineColor, labelColor, tooltipBg } from './chartFactory'
import HoverTip from './HoverTip.vue'

use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

// baseline 场景 图②：均值/P90/P99 分组 bar（SamplerStat 无 p95，用 p90 当尾档）。
//   · baseline 非空 → 当前 vs 历史基线 对比 + P99 改善/退化判定
//   · baseline=null → 只展示本次自己（没设基准 / 自己就是基准），不强行对比
interface VerStat { avg: number; p90: number; p99: number }
const props = defineProps<{
  current: VerStat
  baseline?: VerStat | null
  selfIsBaseline?: boolean
  isDark: boolean
}>()

const comparing = computed(() => !!props.baseline)

// P99 相对基线的改善（负=变快=好），仅对比模式有
const verdict = computed(() => {
  const b = props.baseline
  if (!b || !b.p99) return null
  const d = ((props.current.p99 - b.p99) / b.p99) * 100
  if (d <= -3) return { text: `P99 较基线快 ${(-d).toFixed(0)}% — 改善`, color: '#10b981' }
  if (d >= 3) return { text: `P99 较基线慢 ${d.toFixed(0)}% — 退化`, color: '#ef4444' }
  return { text: 'P99 与基线持平', color: '#f59e0b' }
})

// 单数据（无对比）模式的右上角提示
const soloNote = computed(() => {
  if (comparing.value) return null
  return props.selfIsBaseline
    ? { text: '本次为历史基准', color: '#f59e0b' }
    : { text: '未设基准 · 星标后可对比', color: props.isDark ? 'rgba(255,255,255,0.42)' : 'rgba(0,0,0,0.42)' }
})

const tip = computed(() =>
  '核心问题（基准）：本次相对历史基线，延迟有没有退化？\n\n'
  + '· 设了历史基准 → 当前 vs 基准 分组对比 + P99 改善/退化判定\n'
  + '· 没设 / 自己就是基准 → 只看本次自己的 均值/P90/P99\n\n'
  + '（数据源：接口统计 all 行）',
)

const option = computed(() => {
  const series: any[] = [
    {
      name: '本次', type: 'bar' as const, barWidth: comparing.value ? '28%' : '40%',
      itemStyle: { color: '#3b82f6', borderRadius: [3, 3, 0, 0] },
      data: [props.current.avg, props.current.p90, props.current.p99],
    },
  ]
  if (props.baseline) {
    series.push({
      name: '历史基线', type: 'bar' as const, barWidth: '28%',
      itemStyle: { color: props.isDark ? 'rgba(148,163,184,0.55)' : 'rgba(100,116,139,0.45)', borderRadius: [3, 3, 0, 0] },
      data: [props.baseline.avg, props.baseline.p90, props.baseline.p99],
    })
  }
  return {
    grid: { left: 46, right: 14, top: comparing.value ? 30 : 16, bottom: 24 },
    legend: comparing.value
      ? {
          top: 0, right: 0, itemWidth: 10, itemHeight: 8, itemGap: 12,
          textStyle: { color: labelColor(props.isDark), fontSize: 10 },
          data: ['本次', '历史基线'],
        }
      : { show: false },
    tooltip: {
      trigger: 'axis' as const,
      axisPointer: { type: 'shadow' as const },
      valueFormatter: (v: any) => `${Math.round(v)} ms`,
      ...tooltipBg(props.isDark),
    },
    xAxis: {
      type: 'category' as const,
      data: ['均值', 'P90', 'P99'],
      axisLine: { lineStyle: { color: axisColor(props.isDark) } },
      axisLabel: { color: labelColor(props.isDark), fontSize: 10.5 },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value' as const,
      name: 'ms',
      nameTextStyle: { color: labelColor(props.isDark), fontSize: 10 },
      axisLabel: { color: labelColor(props.isDark), fontSize: 10 },
      axisLine: { show: false },
      splitLine: { lineStyle: { color: gridLineColor(props.isDark) } },
    },
    series,
  }
})
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="flex items-center justify-between gap-2 px-1 mb-1">
      <HoverTip :tip="tip" :is-dark="isDark">
        <span class="text-[11.5px]" :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }">
          {{ comparing ? '版本基准对比（当前 vs 历史）' : '本次延迟分布（均值/P90/P99）' }}
        </span>
      </HoverTip>
      <span v-if="verdict" class="text-[10.5px] tabular-nums" :style="{ color: verdict.color }">{{ verdict.text }}</span>
      <span v-else-if="soloNote" class="text-[10.5px]" :style="{ color: soloNote.color }">{{ soloNote.text }}</span>
    </div>
    <div class="flex-1 min-h-0">
      <VChart :option="option" autoresize style="width: 100%; height: 100%" />
    </div>
  </div>
</template>
