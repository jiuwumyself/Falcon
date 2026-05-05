<script setup lang="ts">
import { computed, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, TitleComponent, LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { RunMetrics, RunMetricsSeries } from '@/types/task'

use([LineChart, GridComponent, TooltipComponent, TitleComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  metrics: RunMetrics | null
  isDark: boolean
}>()

// TG tab 选择；'_overall' 代表"全部接口"概览
const selectedTg = ref<string>('_overall')

const tgKeys = computed(() => Object.keys(props.metrics?.by_tg || {}).sort())

const currentSeries = computed<RunMetricsSeries | null>(() => {
  if (!props.metrics) return null
  if (selectedTg.value === '_overall') return props.metrics.overall
  return props.metrics.by_tg[selectedTg.value] || null
})

function buildOption(
  series: RunMetricsSeries | null,
  field: keyof RunMetricsSeries,
  title: string,
  color: string,
  unit: string,
) {
  const isDark = props.isDark
  const data = series ? series[field] : []
  const axisColor = isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.3)'
  const labelColor = isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)'
  const gridColor = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'

  return {
    title: {
      text: title,
      textStyle: {
        color: labelColor,
        fontSize: 12,
        fontWeight: 'normal' as const,
      },
      left: 8,
      top: 6,
    },
    grid: { left: 50, right: 16, top: 32, bottom: 28 },
    tooltip: {
      trigger: 'axis' as const,
      backgroundColor: isDark ? 'rgba(20,20,30,0.92)' : 'rgba(255,255,255,0.97)',
      borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
      textStyle: { color: isDark ? '#e4e4e7' : '#1a1a2e', fontSize: 11 },
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params
        if (!p) return ''
        const ts = new Date(p.value[0])
        const tsStr = ts.toLocaleTimeString('zh-CN', { hour12: false })
        return `${tsStr}<br/><b>${p.value[1].toFixed(2)} ${unit}</b>`
      },
    },
    xAxis: {
      type: 'time' as const,
      axisLine: { lineStyle: { color: axisColor } },
      axisLabel: { color: labelColor, fontSize: 10 },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value' as const,
      axisLine: { show: false },
      axisLabel: { color: labelColor, fontSize: 10 },
      splitLine: { lineStyle: { color: gridColor } },
    },
    series: [
      {
        type: 'line',
        smooth: true,
        symbol: 'none',
        data,
        lineStyle: { color, width: 2 },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: color + '55' },
              { offset: 1, color: color + '00' },
            ],
          },
        },
      },
    ],
  }
}

const chartCards = computed(() => [
  { title: 'RPS', option: buildOption(currentSeries.value, 'rps', 'RPS', '#3b82f6', 'req/s') },
  { title: 'P99', option: buildOption(currentSeries.value, 'p99_ms', 'P99 响应时间', '#8b5cf6', 'ms') },
  { title: 'ERR', option: buildOption(currentSeries.value, 'error_rate', '错误率', '#ef4444', '%') },
  { title: 'USERS', option: buildOption(currentSeries.value, 'active_users', '活跃用户数', '#10b981', '人') },
])

const hasData = computed(() => {
  const s = currentSeries.value
  if (!s) return false
  return s.rps.length + s.p99_ms.length + s.error_rate.length + s.active_users.length > 0
})
</script>

<template>
  <div class="space-y-3">
    <!-- TG tab 切换 -->
    <div class="flex flex-wrap gap-1.5">
      <button
        type="button"
        class="px-3 py-1.5 rounded-md text-[12px] font-medium transition-all"
        :style="{
          background: selectedTg === '_overall'
            ? '#3b82f6'
            : (isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)'),
          color: selectedTg === '_overall'
            ? '#fff'
            : (isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.65)'),
        }"
        @click="selectedTg = '_overall'"
      >
        全部
      </button>
      <button
        v-for="tg in tgKeys"
        :key="tg"
        type="button"
        class="px-3 py-1.5 rounded-md text-[12px] font-medium transition-all max-w-[200px] truncate"
        :style="{
          background: selectedTg === tg
            ? '#3b82f6'
            : (isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)'),
          color: selectedTg === tg
            ? '#fff'
            : (isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.65)'),
        }"
        @click="selectedTg = tg"
      >
        {{ tg }}
      </button>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
      <div
        v-for="card in chartCards"
        :key="card.title"
        class="rounded-xl p-2 relative"
        :style="{
          background: isDark ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.6)',
          border: isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.06)',
        }"
      >
        <VChart :option="card.option" autoresize style="width:100%; height:180px" />
        <div
          v-if="!hasData"
          class="absolute inset-0 flex items-center justify-center pointer-events-none rounded-xl"
          :style="{ background: isDark ? 'rgba(10,10,10,0.35)' : 'rgba(255,255,255,0.45)' }"
        >
          <div
            class="px-3 py-1.5 rounded-md text-[11.5px]"
            :style="{
              background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)',
              color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.45)',
            }"
          >
            等待运行数据
          </div>
        </div>
      </div>
    </div>

    <div
      v-if="!hasData"
      class="text-center text-[12px] mt-1"
      :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.4)' }"
    >
      暂无指标数据（运行未开始 / 未接入 InfluxDB）
    </div>
  </div>
</template>
