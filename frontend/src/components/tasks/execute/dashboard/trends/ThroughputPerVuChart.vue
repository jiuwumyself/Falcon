<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import VChart from 'vue-echarts'
import { use, connect } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, TitleComponent, LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { SeriesPoint } from '@/types/task'
import { buildSeriesOption, CONNECT_GROUP, statsOf } from './chartFactory'
import HoverTip from './HoverTip.vue'

use([LineChart, GridComponent, TooltipComponent, TitleComponent, LegendComponent, CanvasRenderer])

// 人均吞吐量 = rps[i] / active_users[i]，按时间戳对齐两条序列。
// 加 VU 但 RPS 不涨 → 该曲线下跌 → 系统降级信号（性能老炮判断瓶颈最直接的信号之一）
const props = defineProps<{
  rps: SeriesPoint[]
  vu: SeriesPoint[]
  xRange?: [number, number] | null
  isDark: boolean
}>()

const chartRef = ref<any>(null)

const derived = computed<SeriesPoint[]>(() => {
  if (!props.rps.length || !props.vu.length) return []
  // 按 RPS 时间戳为基准对齐 VU。RPS 来自 InfluxDB 1s 桶（地板对齐时钟），
  // VU 可能来自 dense plannedCurve（从 run.started_at 起算每 1s 一个点）—
  // 两者时间戳通常不严格相等，需要在 ±1.5s 窗口内做最近匹配，否则 exact get
  // 永远 miss，整条人均吞吐量曲线全 0。
  const NEAR_MS = 1500
  const vuArr = props.vu
  const out: SeriesPoint[] = []
  let j = 0
  for (const [t, r] of props.rps) {
    // 双指针推进：vuArr 按 ts 升序，找最接近 t 的 vu 点
    while (j + 1 < vuArr.length && Math.abs(vuArr[j + 1][0] - t) <= Math.abs(vuArr[j][0] - t)) {
      j++
    }
    const [vt, vu] = vuArr[j]
    if (vu <= 0 || Math.abs(vt - t) > NEAR_MS) continue
    out.push([t, r / vu])
  }
  return out
})

const option = computed(() =>
  buildSeriesOption(
    [
      {
        name: 'req/VU/s',
        data: derived.value,
        color: '#06b6d4',
        lineWidth: 1.6,
        area: true,
        formatter: (v: number) => v.toFixed(2),
      },
    ],
    props.isDark,
    'req/VU/s',
    { showLegend: false, gridBottom: 24, xRange: props.xRange ?? null },
  ),
)

const current = computed(() => {
  const arr = derived.value
  if (!arr.length) return 0
  return arr[arr.length - 1][1]
})

const peak = computed(() => statsOf(derived.value).max)

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
  <div class="flex flex-col h-full">
    <div class="flex items-center justify-between px-1 mb-1">
      <HoverTip
        :tip="'核心问题：每多加一个 VU 系统能多榨多少 RPS 出来？\n\n判读条件：\n· 平稳水平 → 线性扩展段，加 VU 仍能成比例提升\n· 缓慢下滑 → 系统开始饱和，但还能扛\n· 急速下滑 → 已过拐点，加 VU 反而拖累\n· 比「总 RPS 不再涨」更早 5-10s 出现拐点信号'"
        :is-dark="isDark"
      >
        <span class="text-[11.5px]"
              :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }">
          人均吞吐量
        </span>
      </HoverTip>
      <div
        class="text-[10.5px] tabular-nums"
        :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
      >
        当前 {{ current.toFixed(2) }} · 峰值 {{ peak.toFixed(2) }}
      </div>
    </div>
    <div class="flex-1 min-h-0">
      <VChart
        ref="chartRef"
        :option="option"
        autoresize
        style="width: 100%; height: 100%"
      />
    </div>
  </div>
</template>
