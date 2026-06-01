<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { axisColor, gridLineColor, labelColor, tooltipBg } from './chartFactory'
import { withAlpha } from './chartColors'
import HoverTip from './HoverTip.vue'

use([ScatterChart, GridComponent, TooltipComponent, CanvasRenderer])

// load 场景 图②：单请求响应时间散点（x=并发 / y=RT）。
// 看「随并发上升，RT 主簇怎么走 + 离群点（长尾）多不多」——补充拐点散点之外的
// 单请求分布视角。
const props = defineProps<{
  points: { x: number; y: number }[]
  isDark: boolean
}>()

const data = computed(() => props.points.map((p) => [p.x, p.y]))
const hasData = computed(() => props.points.length > 0)

const option = computed(() => ({
  grid: { left: 48, right: 16, top: 16, bottom: 34 },
  tooltip: {
    trigger: 'item' as const,
    formatter: (p: any) => `${p.value[0]} VU · ${Number(p.value[1]).toFixed(2)} ms`,
    ...tooltipBg(props.isDark),
  },
  xAxis: {
    type: 'value' as const,
    name: '并发 VU',
    nameLocation: 'middle' as const,
    nameGap: 22,
    nameTextStyle: { color: labelColor(props.isDark), fontSize: 10 },
    axisLine: { lineStyle: { color: axisColor(props.isDark) } },
    axisLabel: { color: labelColor(props.isDark), fontSize: 10 },
    splitLine: { show: false },
  },
  yAxis: {
    type: 'value' as const,
    name: 'RT (ms)',
    nameLocation: 'middle' as const,
    nameGap: 36,
    min: 0,
    nameTextStyle: { color: labelColor(props.isDark), fontSize: 10 },
    axisLine: { show: false },
    axisLabel: { color: labelColor(props.isDark), fontSize: 10 },
    splitLine: { lineStyle: { color: gridLineColor(props.isDark) } },
  },
  series: [
    {
      type: 'scatter' as const,
      symbolSize: 5,
      itemStyle: { color: withAlpha('#10b981', 0.42) },
      data: data.value,
    },
  ],
}))
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="flex items-center px-1 mb-1">
      <HoverTip
        :tip="'核心问题（负载）：并发上来后，单请求延迟分布怎么变？\n\n判读：\n· 主簇随 VU 缓慢上移 → 正常\n· 离群点（上方散点）随 VU 增多 → 长尾恶化，少量请求被拖慢\n· 主簇突然整体抬高 → 进入拐点后区'"
        :is-dark="isDark"
      >
        <span class="text-[11.5px]" :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }">
          请求响应时间散点（按并发）
        </span>
      </HoverTip>
    </div>
    <div class="flex-1 min-h-0">
      <VChart v-if="hasData" :option="option" autoresize style="width: 100%; height: 100%" />
      <div
        v-else
        class="h-full flex items-center justify-center text-[11px]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)' }"
      >暂无数据</div>
    </div>
  </div>
</template>
