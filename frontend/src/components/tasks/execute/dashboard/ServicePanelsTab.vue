<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Server, Cpu, HardDrive, Loader, AlertCircle, RefreshCw } from 'lucide-vue-next'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent, TitleComponent, TooltipComponent, LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { prometheusSourcesApi } from '@/lib/api'
import type { PrometheusMetricSeries, PrometheusMetricsResponse, Task, TaskRun } from '@/types/task'

use([LineChart, GridComponent, TitleComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  task: Task
  run: TaskRun | null
  isDark: boolean
}>()

// ── 时间窗 ──
const TIME_RANGE_OPTIONS = [
  { label: '1h', seconds: 3600 },
  { label: '3h', seconds: 10800 },
  { label: '6h', seconds: 21600 },
  { label: '24h', seconds: 86400 },
]
const selectedRangeIdx = ref(0)
const timeRange = computed(() => TIME_RANGE_OPTIONS[selectedRangeIdx.value].seconds)

// ── 选中服务 ──
const selectedService = ref<string>('')
const services = computed(() => props.task.service_names || [])

watch(services, (s) => {
  if (s.length && !s.includes(selectedService.value)) {
    selectedService.value = s[0]
  }
}, { immediate: true })

// ── 数据获取 ──
const metricsMap = ref<Record<string, PrometheusMetricsResponse>>({})
const loading = ref(false)
const error = ref('')
const loadedAt = ref<number>(0)

async function fetchMetrics() {
  const sourceId = props.task.prometheus_source
  const job = selectedService.value
  if (!sourceId || !job) {
    metricsMap.value = {}
    return
  }

  loading.value = true
  error.value = ''
  try {
    const end = Math.floor(Date.now() / 1000)
    const start = end - timeRange.value
    const data = await prometheusSourcesApi.metrics(sourceId, {
      job,
      start,
      end,
      step: `${Math.max(15, Math.floor(timeRange.value / 240))}s`,
    })
    metricsMap.value = { ...metricsMap.value, [job]: data }
    loadedAt.value = Date.now()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

// 切换服务/时间范围时重新拉数据
watch([selectedService, timeRange], () => { void fetchMetrics() })
onMounted(() => { void fetchMetrics() })

// ── 自动刷新（run 运行中时每 30s 刷新）──
let autoRefreshTimer: ReturnType<typeof setInterval> | null = null
const isRunActive = computed(() =>
  !!props.run && ['pre_checking', 'pending', 'running', 'cancelling'].includes(props.run.status),
)

watch(isRunActive, (active) => {
  if (active) {
    autoRefreshTimer = setInterval(() => void fetchMetrics(), 30000)
  } else {
    if (autoRefreshTimer) clearInterval(autoRefreshTimer)
    autoRefreshTimer = null
  }
}, { immediate: true })

onUnmounted(() => {
  if (autoRefreshTimer) clearInterval(autoRefreshTimer)
})

// ── ECharts 选项 ──
const axisColor = computed(() => props.isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.5)')
const splitColor = computed(() => props.isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)')

const currentMetrics = computed<PrometheusMetricsResponse | null>(
  () => metricsMap.value[selectedService.value] ?? null,
)

function makeChartOption(
  title: string,
  color: string,
  series: { name: string; data: { ts: number; value: number }[] }[],
) {
  return {
    title: { text: title, left: 8, top: 4, textStyle: { fontSize: 11, color: axisColor.value } },
    grid: { top: 30, left: 46, right: 14, bottom: 24 },
    tooltip: { trigger: 'axis' },
    legend: series.length > 1
      ? { show: true, bottom: 0, textStyle: { fontSize: 9, color: axisColor.value } }
      : undefined,
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: axisColor.value } },
      splitLine: { show: false },
      axisLabel: { fontSize: 9, color: axisColor.value },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      splitLine: { lineStyle: { color: splitColor.value } },
      axisLabel: { fontSize: 9, color: axisColor.value },
    },
    series: series.map((s, i) => ({
      type: 'line' as const,
      name: s.name,
      data: s.data.map((d) => [d.ts * 1000, d.value]),
      smooth: true,
      symbol: 'none',
      lineStyle: { width: 1.5, color: i === 0 ? color : '#a78bfa' },
      areaStyle: i === 0 ? { color, opacity: 0.18 } : undefined,
    })),
  }
}

const cpuOption = computed(() => {
  const m = currentMetrics.value
  if (!m) return null
  const cpuSeries = m.cpu_usage
  const cadvisorCpu = m.cpu_usage_cadvisor
  const lines: { name: string; data: { ts: number; value: number }[] }[] = []
  if (cpuSeries && cpuSeries.data.length) lines.push({ name: cpuSeries.display_name, data: cpuSeries.data })
  if (cadvisorCpu && cadvisorCpu.data.length) lines.push({ name: cadvisorCpu.display_name, data: cadvisorCpu.data })
  if (!lines.length) return null
  return makeChartOption('CPU', '#3b82f6', lines)
})

const memOption = computed(() => {
  const m = currentMetrics.value
  if (!m) return null
  const memSeries = m.memory_usage
  const cadvisorMem = m.memory_usage_cadvisor
  const lines: { name: string; data: { ts: number; value: number }[] }[] = []
  if (memSeries && memSeries.data.length) lines.push({ name: memSeries.display_name, data: memSeries.data })
  if (cadvisorMem && cadvisorMem.data.length) lines.push({ name: cadvisorMem.display_name, data: cadvisorMem.data })
  if (!lines.length) return null
  return makeChartOption('内存', '#10b981', lines)
})

const hasAnyData = computed(() => !!cpuOption.value || !!memOption.value)
</script>

<template>
  <div class="h-full overflow-y-auto p-4">
    <!-- 无服务选择提示 -->
    <p v-if="!services.length" class="text-[12px] py-6 text-center"
       :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">
      <Server :size="20" class="inline-block mb-2" />
      <br>请在 Step 2 选择服务以查看监控面板。
    </p>

    <!-- 无数据源提示 -->
    <p v-else-if="!task.prometheus_source" class="text-[12px] py-6 text-center"
       :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">
      <Server :size="20" class="inline-block mb-2" />
      <br>未关联 Prometheus 数据源，请在 Step 2 重新选择服务。
    </p>

    <!-- 主面板 -->
    <template v-else>
      <!-- 工具栏：服务切换 + 时间范围 + 刷新 -->
      <div class="flex items-center gap-2 mb-3 flex-wrap">
        <!-- 服务标签切换 -->
        <button
          v-for="svc in services"
          :key="svc"
          class="px-2.5 py-1 rounded text-[11px] cursor-pointer"
          :style="{
            background: selectedService === svc
              ? (isDark ? 'rgba(59,130,246,0.2)' : 'rgba(59,130,246,0.12)')
              : (isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)'),
            color: selectedService === svc
              ? (isDark ? '#93c5fd' : '#2563eb')
              : (isDark ? 'rgba(255,255,255,0.65)' : 'rgba(0,0,0,0.7)'),
            border: `1px solid ${selectedService === svc
              ? (isDark ? 'rgba(59,130,246,0.35)' : 'rgba(59,130,246,0.3)')
              : 'transparent'}`,
          }"
          @click="selectedService = svc"
        >
          <Server :size="10" class="inline mr-1" />
          {{ svc }}
        </button>

        <span class="flex-1" />

        <!-- 时间范围 -->
        <div class="flex items-center gap-1">
          <button
            v-for="(opt, i) in TIME_RANGE_OPTIONS"
            :key="opt.label"
            class="px-2 py-0.5 rounded text-[10px] cursor-pointer"
            :style="{
              background: selectedRangeIdx === i
                ? (isDark ? 'rgba(59,130,246,0.18)' : 'rgba(59,130,246,0.1)')
                : 'transparent',
              color: selectedRangeIdx === i
                ? '#3b82f6'
                : (isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)'),
            }"
            @click="selectedRangeIdx = i"
          >{{ opt.label }}</button>
        </div>

        <!-- 刷新 -->
        <button
          class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] cursor-pointer"
          :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }"
          :disabled="loading"
          @click="fetchMetrics"
        >
          <RefreshCw :size="10" :class="{ 'animate-spin': loading }" />
          刷新
        </button>
      </div>

      <!-- 错误提示 -->
      <p v-if="error" class="text-[11px] text-red-500 flex items-center gap-1 mb-2">
        <AlertCircle :size="11" /> {{ error }}
      </p>

      <!-- 加载中 -->
      <div v-if="loading && !hasAnyData" class="flex items-center gap-2 py-8 justify-center"
           :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">
        <Loader :size="14" class="animate-spin" />
        <span class="text-[12px]">加载监控数据…</span>
      </div>

      <!-- 无数据 -->
      <div v-else-if="!loading && !hasAnyData" class="text-[12px] py-8 text-center"
           :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">
        <Cpu :size="20" class="inline-block mb-2" />
        <br>所选服务（{{ selectedService }}）暂无 Prometheus 监控数据。
      </div>

      <!-- 图表区域 -->
      <div v-else class="grid grid-cols-1 gap-3">
        <!-- CPU 图表 -->
        <div v-if="cpuOption"
             class="rounded-lg p-1"
             :style="{ background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)' }">
          <v-chart :option="cpuOption" :init-options="{ renderer: 'canvas' }" style="height: 200px" autoresize />
        </div>

        <!-- 内存图表 -->
        <div v-if="memOption"
             class="rounded-lg p-1"
             :style="{ background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)' }">
          <v-chart :option="memOption" :init-options="{ renderer: 'canvas' }" style="height: 200px" autoresize />
        </div>
      </div>

      <!-- 底部时间戳 -->
      <p v-if="loadedAt" class="text-[10px] mt-2 text-center"
         :style="{ color: isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.35)' }">
        数据更新于 {{ new Date(loadedAt).toLocaleTimeString() }}
        <template v-if="isRunActive"> · 运行中每 30s 自动刷新</template>
      </p>
    </template>
  </div>
</template>
