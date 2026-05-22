<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Server, Cpu, Loader, AlertCircle, RefreshCw, ChevronDown, Clock } from 'lucide-vue-next'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent, TitleComponent, TooltipComponent, LegendComponent,
  DataZoomComponent, MarkLineComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { onClickOutside } from '@vueuse/core'
import { prometheusSourcesApi } from '@/lib/api'
import type { FluentBitMetricsResponse, FluentBitPodMetric, PrometheusMetricsResponse, Task, TaskRun } from '@/types/task'

use([LineChart, GridComponent, TitleComponent, TooltipComponent, LegendComponent, DataZoomComponent, MarkLineComponent, CanvasRenderer])

const props = defineProps<{
  task: Task
  run: TaskRun | null
  isDark: boolean
}>()

// ── 时间窗 ──────────────────────────────────────────────
const QUICK_RANGES = [
  { label: '5m', seconds: 300 },
  { label: '15m', seconds: 900 },
  { label: '30m', seconds: 1800 },
  { label: '1h', seconds: 3600 },
  { label: '3h', seconds: 10800 },
  { label: '6h', seconds: 21600 },
  { label: '12h', seconds: 43200 },
  { label: '24h', seconds: 86400 },
  { label: '2d', seconds: 172800 },
  { label: '7d', seconds: 604800 },
]
const REFRESH_INTERVALS = [
  { label: '关闭', ms: 0 },
  { label: '30s', ms: 30000 },
  { label: '1m', ms: 60000 },
  { label: '5m', ms: 300000 },
]

const selectedRangeIdx = ref(3) // 默认 1h
const timeRange = computed(() => QUICK_RANGES[selectedRangeIdx.value].seconds)
const showTimePicker = ref(false)
const refreshIntervalIdx = ref(0)
const customFrom = ref('')
const customTo = ref('')
const isCustomRange = ref(false)
const customRangeSeconds = ref(3600)

const timePickerRef = ref<HTMLElement>()
onClickOutside(timePickerRef, () => { showTimePicker.value = false })

const currentTimeRangeLabel = computed(() => {
  if (isCustomRange.value) return '自定义范围'
  return `最近 ${QUICK_RANGES[selectedRangeIdx.value].label}`
})

function toDatetimeLocal(d: Date): string {
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

watch(showTimePicker, (show) => {
  if (show) {
    const now = new Date()
    const from = new Date(now.getTime() - effectiveRangeSeconds.value * 1000)
    customFrom.value = toDatetimeLocal(from)
    customTo.value = toDatetimeLocal(now)
  }
})

function selectQuickRange(idx: number) {
  selectedRangeIdx.value = idx
  isCustomRange.value = false
  showTimePicker.value = false
}

function applyCustomRange() {
  if (!customFrom.value || !customTo.value) return
  const from = new Date(customFrom.value).getTime() / 1000
  const to = new Date(customTo.value).getTime() / 1000
  if (isNaN(from) || isNaN(to) || from >= to) return
  customRangeSeconds.value = Math.round(to - from)
  isCustomRange.value = true
  showTimePicker.value = false
}

const effectiveRangeSeconds = computed(() =>
  isCustomRange.value ? customRangeSeconds.value : timeRange.value,
)

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
  const service = selectedService.value
  if (!sourceId || !service) { metricsMap.value = {}; return }

  loading.value = true
  error.value = ''
  try {
    const end = Math.floor(Date.now() / 1000)
    const start = end - effectiveRangeSeconds.value
    const step = Math.max(15, Math.floor(effectiveRangeSeconds.value / 240))
    // 性能优化：只查询页面实际需要的指标（而非全部 14 个）
    // cpu_usage, memory_usage 用于主图表
    // network_rx, network_tx 用于底部统计
    // disk_read, disk_write 用于磁盘图表
    // cpu_usage_by_pod, memory_usage_by_pod 用于 Pod 图表面板
    const neededMetrics = 'cpu_usage,memory_usage,network_rx,network_tx,disk_read,disk_write,cpu_usage_by_pod,memory_usage_by_pod'
    const data = await prometheusSourcesApi.metrics(sourceId, {
      service, start, end, step: `${step}s`, metrics: neededMetrics,
    })
    metricsMap.value = { ...metricsMap.value, [service]: data }
    loadedAt.value = Date.now()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

watch([selectedService, effectiveRangeSeconds], () => { void fetchMetrics() })
onMounted(() => { void fetchMetrics() })

// ── 自动刷新 ──
let autoRefreshTimer: ReturnType<typeof setInterval> | null = null
const isRunActive = computed(() =>
  !!props.run && ['pre_checking', 'pending', 'running', 'cancelling'].includes(props.run.status),
)
const refreshMs = computed(() => REFRESH_INTERVALS[refreshIntervalIdx.value].ms)

function startAutoRefresh() {
  stopAutoRefresh()
  const ms = isRunActive.value
    ? Math.min(30000, refreshMs.value || 30000)
    : refreshMs.value
  if (ms > 0) autoRefreshTimer = setInterval(() => void fetchMetrics(), ms)
}
function stopAutoRefresh() {
  if (autoRefreshTimer) clearInterval(autoRefreshTimer)
  autoRefreshTimer = null
}

watch([isRunActive, refreshMs], () => { startAutoRefresh() }, { immediate: true })
onUnmounted(() => { stopAutoRefresh() })

// ── 统计计算 ──
interface Stats { avg: number; min: number; max: number; current: number }
const EMPTY_STATS: Stats = { avg: 0, min: 0, max: 0, current: 0 }

function computeStats(data: { ts: number; value: number }[]): Stats {
  if (!data.length) return EMPTY_STATS
  const vals = data.map(d => d.value)
  return {
    avg: vals.reduce((a, b) => a + b, 0) / vals.length,
    min: Math.min(...vals),
    max: Math.max(...vals),
    current: vals[vals.length - 1],
  }
}

// ── 格式化 ──
const axisColor = computed(() => props.isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.5)')
const splitColor = computed(() => props.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)')
const panelBg = computed(() => props.isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)')
const dropdownBg = computed(() => props.isDark ? '#1e1e2e' : '#ffffff')
const dropdownBorder = computed(() => props.isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.1)')
const inputBg = computed(() => props.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)')

function formatCpuValue(v: number): string {
  return v.toFixed(1) + '%'
}

function formatMemValue(v: number): string {
  return v.toFixed(1) + '%'
}

function formatNetDiskValue(v: number): string {
  if (v >= 1024) return (v / 1024).toFixed(1) + ' MB/s'
  return v.toFixed(1) + ' KB/s'
}

const currentMetrics = computed<PrometheusMetricsResponse | null>(
  () => metricsMap.value[selectedService.value] ?? null,
)

// ── ECharts 选项 ──
function makeChartOption(
  title: string,
  unit: 'cpu' | 'memory' | 'netdisk',
  color: string,
  series: { name: string; data: { ts: number; value: number }[] }[],
) {
  const formatValue = unit === 'cpu' ? formatCpuValue : unit === 'memory' ? formatMemValue : formatNetDiskValue

  // 计算所有数据点的 min/max，动态设置纵坐标范围（对标 Grafana 自适应缩放）
  const allValues = series.flatMap(s => s.data.map(d => d.value))
  let yMin: number | undefined
  let yMax: number | undefined
  if (allValues.length > 0) {
    const dataMin = Math.min(...allValues)
    const dataMax = Math.max(...allValues)
    const span = dataMax - dataMin
    if (span > 0.01) {
      // 有明显波动：上下各留 30% 余量，让波动曲线充满图表
      yMin = Math.max(0, dataMin - span * 0.3)
      yMax = dataMax + span * 0.3
    } else {
      // 数据几乎是直线：以数据中心为基准，留 ±1% 余量
      const mid = (dataMin + dataMax) / 2
      yMin = Math.max(0, mid - 1)
      yMax = mid + 1
    }
  }
  return {
    title: {
      text: title,
      left: 8, top: 4,
      textStyle: { fontSize: 11, color: axisColor.value },
    },
    grid: { top: 30, left: 54, right: 14, bottom: 16 },
    tooltip: {
      trigger: 'axis' as const,
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params
        const t = new Date(p.value[0]).toLocaleTimeString()
        const v = formatValue(p.value[1])
        return `${p.seriesName}<br/>${t}<br/><b>${v}</b>`
      },
    },
    legend: { show: false },
    dataZoom: [
      {
        type: 'inside' as const,
        xAxisIndex: 0,
        filterMode: 'filter' as const,
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
        moveOnMouseWheel: false,
      },
    ],
    xAxis: {
      type: 'time' as const,
      axisLine: { lineStyle: { color: axisColor.value } },
      splitLine: { show: false },
      axisLabel: { fontSize: 9, color: axisColor.value },
    },
    yAxis: {
      type: 'value' as const,
      min: yMin,
      max: yMax,
      axisLine: { show: false },
      splitLine: { lineStyle: { color: splitColor.value } },
      axisLabel: {
        fontSize: 9,
        color: axisColor.value,
        formatter: (v: number) => formatValue(v),
      },
    },
    series: series.map((s, i) => ({
      type: 'line' as const,
      name: s.name,
      data: s.data.map((d) => [d.ts * 1000, d.value]),
      smooth: true,
      symbol: 'none',
      lineStyle: { width: 1.5, color: i === 0 ? color : '#a78bfa' },
      areaStyle: i === 0 ? { color, opacity: 0.12 } : undefined,
    })),
  }
}

const cpuStats = computed(() => {
  const m = currentMetrics.value
  if (!m?.cpu_usage?.data.length) return EMPTY_STATS
  return computeStats(m.cpu_usage.data)
})
const memStats = computed(() => {
  const m = currentMetrics.value
  if (!m?.memory_usage?.data.length) return EMPTY_STATS
  return computeStats(m.memory_usage.data)
})
const netRxStats = computed(() => {
  const m = currentMetrics.value
  if (!m?.network_rx?.data.length) return EMPTY_STATS
  return computeStats(m.network_rx.data)
})
const netTxStats = computed(() => {
  const m = currentMetrics.value
  if (!m?.network_tx?.data.length) return EMPTY_STATS
  return computeStats(m.network_tx.data)
})
const diskReadStats = computed(() => {
  const m = currentMetrics.value
  if (!m?.disk_read?.data.length) return EMPTY_STATS
  return computeStats(m.disk_read.data)
})
const diskWriteStats = computed(() => {
  const m = currentMetrics.value
  if (!m?.disk_write?.data.length) return EMPTY_STATS
  return computeStats(m.disk_write.data)
})

const cpuOption = computed(() => {
  const m = currentMetrics.value
  if (!m) return null
  const s = m.cpu_usage
  if (!s?.data.length) return null
  return makeChartOption('CPU 使用率', 'cpu', '#3b82f6', [{ name: s.display_name, data: s.data }])
})
const memOption = computed(() => {
  const m = currentMetrics.value
  if (!m) return null
  const wss = m.memory_usage
  const rss = m.memory_rss_usage
  if (!wss?.data.length && !rss?.data.length) return null
  const series = []
  if (wss?.data.length) series.push({ name: 'WSS', data: wss.data })
  if (rss?.data.length) series.push({ name: 'RSS', data: rss.data })
  return makeChartOption('内存使用量', 'memory', '#10b981', series)
})
const networkOption = computed(() => {
  const m = currentMetrics.value
  if (!m) return null
  const rx = m.network_rx
  const tx = m.network_tx
  if (!rx?.data.length && !tx?.data.length) return null
  const series = []
  if (rx?.data.length) series.push({ name: '接收 RX', data: rx.data })
  if (tx?.data.length) series.push({ name: '发送 TX', data: tx.data })
  return makeChartOption('网络流量', 'netdisk', '#8b5cf6', series)
})
const diskOption = computed(() => {
  const m = currentMetrics.value
  if (!m) return null
  const rd = m.disk_read
  const wr = m.disk_write
  if (!rd?.data.length && !wr?.data.length) return null
  const series = []
  if (rd?.data.length) series.push({ name: '读取 Read', data: rd.data })
  if (wr?.data.length) series.push({ name: '写入 Write', data: wr.data })
  return makeChartOption('磁盘 I/O', 'netdisk', '#f59e0b', series)
})
const hasAnyData = computed(() => !!cpuOption.value || !!memOption.value || !!networkOption.value || !!diskOption.value)

// ── per-pod 图表 ────────────────────────────
// pod 颜色池：参考 Grafana 风格多彩线
const POD_COLORS = [
  '#5794f2', '#f2cc0c', '#37872d', '#c4162a', '#ff780a',
  '#806eb7', '#82b5d8', '#e5a216', '#6ccf8e', '#ff4f55',
  '#e0752d', '#967302', '#bf1b00', '#0a50a1', '#694b00',
]

function makePodChartOption(
  title: string,
  unit: 'cpu' | 'memory',
  pods: Record<string, { ts: number; value: number }[]>,
  secondaryPods?: Record<string, { ts: number; value: number }[]>,  // 第二组数据（如 RSS）
  secondaryLabel?: string,  // 第二组图例前缀，如 'RSS'
) {
  const formatValue = unit === 'cpu' ? formatCpuValue : formatMemValue
  const podNames = Object.keys(pods).sort()

  // 计算全部数据的 min/max 动态调节纵坐标
  const allPodsDatas = [pods, secondaryPods].filter(Boolean) as Record<string, { ts: number; value: number }[]>[]
  const allValues = allPodsDatas.flatMap(p => Object.values(p).flatMap(arr => arr.map(d => d.value)))
  let yMin: number | undefined
  let yMax: number | undefined
  if (allValues.length > 0) {
    const dataMin = Math.min(...allValues)
    const dataMax = Math.max(...allValues)
    const span = dataMax - dataMin
    if (span > 0.01) {
      yMin = Math.max(0, dataMin - span * 0.3)
      yMax = dataMax + span * 0.3
    } else {
      const mid = (dataMin + dataMax) / 2
      yMin = Math.max(0, mid - 1)
      yMax = mid + 1
    }
  }

  // 主线组（WSS 或 CPU）
  const primarySeries = podNames.map((podName, i) => ({
    type: 'line' as const,
    name: podName,
    data: pods[podName].map(d => [d.ts * 1000, d.value]),
    smooth: true,
    symbol: 'none',
    lineStyle: { width: 1.2, color: POD_COLORS[i % POD_COLORS.length] },
    areaStyle: undefined,
  }))

  // 副线组（RSS）—— 相同颜色但虚线、细幂
  const secondarySeries = secondaryPods
    ? podNames
        .filter(p => secondaryPods[p]?.length)
        .map((podName, i) => ({
          type: 'line' as const,
          name: `${secondaryLabel ?? 'RSS'}: ${podName}`,
          data: secondaryPods[podName].map(d => [d.ts * 1000, d.value]),
          smooth: true,
          symbol: 'none',
          lineStyle: { width: 0.8, color: POD_COLORS[i % POD_COLORS.length], type: 'dashed' as const },
          areaStyle: undefined,
        }))
    : []

  return {
    title: {
      text: title,
      left: 8, top: 4,
      textStyle: { fontSize: 11, color: axisColor.value },
    },
    grid: { top: 30, left: 54, right: 14, bottom: 16 },
    tooltip: {
      trigger: 'axis' as const,
      formatter: (params: any) => {
        const arr = Array.isArray(params) ? params : [params]
        const t = new Date(arr[0].value[0]).toLocaleTimeString()
        const lines = arr.map((p: any) =>
          `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color};margin-right:4px;"></span>${p.seriesName}: <b>${formatValue(p.value[1])}</b>`,
        ).join('<br/>')
        return `${t}<br/>${lines}`
      },
    },
    legend: {
      show: false,
    },
    dataZoom: [
      {
        type: 'inside' as const,
        xAxisIndex: 0,
        filterMode: 'filter' as const,
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
        moveOnMouseWheel: false,
      },
    ],
    xAxis: {
      type: 'time' as const,
      axisLine: { lineStyle: { color: axisColor.value } },
      splitLine: { show: false },
      axisLabel: { fontSize: 9, color: axisColor.value },
    },
    yAxis: {
      type: 'value' as const,
      min: yMin,
      max: yMax,
      axisLine: { show: false },
      splitLine: { lineStyle: { color: splitColor.value } },
      axisLabel: {
        fontSize: 9,
        color: axisColor.value,
        formatter: (v: number) => formatValue(v),
      },
    },
    series: [...primarySeries, ...secondarySeries],
  }
}

const cpuByPodOption = computed(() => {
  const m = currentMetrics.value
  if (!m) return null
  const s = m.cpu_usage_by_pod
  if (!s?.pods || Object.keys(s.pods).length === 0) return null
  return makePodChartOption('Pod CPU 使用率', 'cpu', s.pods)
})

const memByPodOption = computed(() => {
  const m = currentMetrics.value
  if (!m) return null
  const wssSeries = m.memory_usage_by_pod
  const rssSeries = m.memory_rss_by_pod
  const wssPods = wssSeries?.pods ?? {}
  const rssPods = rssSeries?.pods ?? {}
  if (!Object.keys(wssPods).length && !Object.keys(rssPods).length) return null
  // 以 WSS 为主线，如果无 WSS 则以 RSS 为主
  const primaryPods = Object.keys(wssPods).length ? wssPods : rssPods
  const secPods = Object.keys(wssPods).length && Object.keys(rssPods).length ? rssPods : undefined
  return makePodChartOption('Pod 内存使用率', 'memory', primaryPods, secPods, 'RSS')
})

const cpuByPodChartRef = ref()
const memByPodChartRef = ref()

// ── 图表交互：双击重置缩放 / 扩展时间范围 ──
const cpuChartRef = ref()
const memChartRef = ref()
const networkChartRef = ref()
const diskChartRef = ref()

function handleDblClick(chartType: 'cpu' | 'mem' | 'network' | 'disk') {
  const chartRef = chartType === 'cpu' ? cpuChartRef : chartType === 'mem' ? memChartRef : chartType === 'network' ? networkChartRef : diskChartRef
  // vue-echarts: ref 可能直接是 ECharts 实例，也可能是组件实例（.chart 属性）
  const instance = chartRef.value?.chart ?? chartRef.value
  if (instance && typeof instance.dispatchAction === 'function') {
    try {
      const option = instance.getOption()
      const zoom = option?.dataZoom?.[0]
      if (zoom && (zoom.start > 1 || zoom.end < 99)) {
        // 已缩放 → 重置到全范围
        instance.dispatchAction({ type: 'dataZoom', start: 0, end: 100 })
      } else {
        // 全范围 → 跳到下一档更大的时间范围
        const nextIdx = Math.min(selectedRangeIdx.value + 1, QUICK_RANGES.length - 1)
        if (nextIdx > selectedRangeIdx.value) {
          selectedRangeIdx.value = nextIdx
          isCustomRange.value = false
        }
      }
    } catch {
      // fallback: 直接重置
      instance.dispatchAction({ type: 'dataZoom', start: 0, end: 100 })
    }
  }
}

// ── View 全屏功能 ───────────────────────────
type ViewPanelId = 'cpu' | 'mem' | 'podCpu' | 'podMem' | 'disk' | 'network'
const viewPanel = ref<ViewPanelId | null>(null)

function openView(id: ViewPanelId) {
  viewPanel.value = id
}
function closeView() {
  viewPanel.value = null
}

// ESC 关闭全屏
onMounted(() => {
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeView()
  })
})

// 当前 view 对应的 option 和标题
const viewOption = computed(() => {
  switch (viewPanel.value) {
    case 'cpu': return cpuOption.value
    case 'mem': return memOption.value
    case 'podCpu': return cpuByPodOption.value
    case 'podMem': return memByPodOption.value
    case 'disk': return diskOption.value
    case 'network': return networkOption.value
    default: return null
  }
})
const VIEW_TITLES: Record<ViewPanelId, string> = {
  cpu: 'CPU 使用率',
  mem: '内存使用量',
  podCpu: 'Pod CPU 使用率',
  podMem: 'Pod 内存使用率',
  disk: '磁盘 I/O',
  network: '网络流量',
}

// ── Pod 统计表：每个 pod 的 max / current ────────────
interface PodStat { name: string; max: number; current: number; color: string }

function computePodStats(
  pods: Record<string, { ts: number; value: number }[]>,
): PodStat[] {
  const podNames = Object.keys(pods).sort()
  return podNames
    .map((name, i) => {
      const vals = pods[name].map(d => d.value)
      return {
        name,
        max: vals.length ? Math.max(...vals) : 0,
        current: vals.length ? vals[vals.length - 1] : 0,
        color: POD_COLORS[i % POD_COLORS.length],
      }
    })
    .sort((a, b) => b.current - a.current)
}

const cpuPodStats = computed<PodStat[]>(() => {
  const pods = currentMetrics.value?.cpu_usage_by_pod?.pods
  return pods ? computePodStats(pods) : []
})

const memPodStats = computed<PodStat[]>(() => {
  const pods = currentMetrics.value?.memory_usage_by_pod?.pods
  return pods ? computePodStats(pods) : []
})

// Pod 图表点击联动：null = 全部显示，字符串 = 单独显示该 pod
const activeCpuPod = ref<string | null>(null)
const activeMemPod = ref<string | null>(null)

function togglePodInChart(
  chartRef: any,
  podName: string,
  allPodNames: string[],
  activeRef: { value: string | null },
) {
  const instance = chartRef?.chart ?? chartRef
  if (!instance || typeof instance.dispatchAction !== 'function') return

  if (activeRef.value === podName) {
    // 再次点击同一 pod → 恢复全部
    activeRef.value = null
    allPodNames.forEach(name => {
      instance.dispatchAction({ type: 'legendSelect', name })
    })
  } else {
    // 点击新 pod → 隐藏其他，只显示该 pod
    activeRef.value = podName
    allPodNames.forEach(name => {
      if (name === podName) {
        instance.dispatchAction({ type: 'legendSelect', name })
      } else {
        instance.dispatchAction({ type: 'legendUnSelect', name })
      }
    })
  }
}

function clickCpuPod(podName: string) {
  togglePodInChart(cpuByPodChartRef.value, podName, cpuPodStats.value.map(p => p.name), activeCpuPod)
}
function clickMemPod(podName: string) {
  togglePodInChart(memByPodChartRef.value, podName, memPodStats.value.map(p => p.name), activeMemPod)
}

// ── Fluent-bit 监控表格 ────────────────────────────────
const fbData = ref<FluentBitMetricsResponse | null>(null)
const fbLoading = ref(false)
const fbError = ref('')
const fbLoadedAt = ref(0)

async function fetchFluentBit() {
  if (!props.task.prometheus_source) return
  fbLoading.value = true
  fbError.value = ''
  try {
    fbData.value = await prometheusSourcesApi.fluentBit()
    fbLoadedAt.value = Date.now()
  } catch (e) {
    fbError.value = e instanceof Error ? e.message : String(e)
  } finally {
    fbLoading.value = false
  }
}

// 首次载入和同步刷新
onMounted(() => { void fetchFluentBit() })
watch(isRunActive, () => { void fetchFluentBit() })

function fmtNum(v: number | null | undefined, decimals = 1): string {
  if (v == null || isNaN(v)) return '-'
  return v.toFixed(decimals)
}
function fmtKbs(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return '-'
  if (v >= 1024) return (v / 1024).toFixed(1) + ' MB/s'
  return v.toFixed(1) + ' KB/s'
}
// CPU% 限制到 0~100范围，保留两位小数
function fmtCpuPct(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return '-'
  return Math.min(100, Math.max(0, v)).toFixed(2) + '%'
}
// CPU 核数：millicores 转换为核数（如 1000m → 1.00，4000m → 4.00）
function fmtCpuCores(millicores: number | null | undefined): string {
  if (millicores == null || isNaN(millicores)) return '-'
  return (millicores / 1000).toFixed(2)
}
// 内存 GiB：MB 转换为 GiB（如 8192MB → 8.00GiB）
function fmtMemGiB(mb: number | null | undefined): string {
  if (mb == null || isNaN(mb)) return '-'
  return (mb / 1024).toFixed(2) + ' GiB'
}
// 磁盘使用量：bytes 自动换算为 GiB/MiB（如 1073741824 → 1.00 GiB，524288000 → 500.00 MiB）
function fmtDiskUsage(bytes: number | null | undefined): string {
  if (bytes == null || isNaN(bytes)) return '-'
  if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(2) + ' GiB'
  if (bytes >= 1048576) return (bytes / 1048576).toFixed(2) + ' MiB'
  return bytes.toFixed(0) + ' B'
}
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
      <!-- ── 工具栏 ── -->
      <div class="flex items-center gap-2 mb-3 flex-wrap">
        <!-- 服务标签切换 -->
        <button
          v-for="svc in services" :key="svc"
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

        <!-- Grafana 风格时间筛选器 -->
        <div ref="timePickerRef" class="relative">
          <button
            class="flex items-center gap-1 px-2.5 py-1 rounded text-[11px] cursor-pointer"
            :style="{
              background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)',
              border: `1px solid ${isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)'}`,
              color: isDark ? 'rgba(255,255,255,0.8)' : 'rgba(0,0,0,0.75)',
            }"
            @click="showTimePicker = !showTimePicker"
          >
            <Clock :size="11" />
            {{ currentTimeRangeLabel }}
            <ChevronDown :size="11" />
          </button>

          <!-- 下拉面板 -->
          <div
            v-if="showTimePicker"
            class="absolute right-0 top-full mt-1 z-50 w-72 rounded-lg shadow-xl overflow-hidden"
            :style="{
              background: dropdownBg,
              border: `1px solid ${dropdownBorder}`,
            }"
          >
            <!-- 快捷范围 -->
            <div class="p-2.5">
              <div class="text-[9px] mb-1.5 font-medium"
                   :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.45)' }">
                快捷范围
              </div>
              <div class="grid grid-cols-5 gap-1">
                <button
                  v-for="(opt, i) in QUICK_RANGES" :key="opt.label"
                  class="px-1.5 py-1 rounded text-[10px] cursor-pointer text-center"
                  :style="{
                    background: selectedRangeIdx === i && !isCustomRange
                      ? 'rgba(59,130,246,0.15)' : 'transparent',
                    color: selectedRangeIdx === i && !isCustomRange
                      ? '#3b82f6' : (isDark ? 'rgba(255,255,255,0.65)' : 'rgba(0,0,0,0.65)'),
                    border: `1px solid ${selectedRangeIdx === i && !isCustomRange
                      ? 'rgba(59,130,246,0.3)' : 'transparent'}`,
                  }"
                  @click="selectQuickRange(i)"
                >{{ opt.label }}</button>
              </div>
            </div>

            <!-- 分隔线 -->
            <div :style="{ borderTop: `1px solid ${dropdownBorder}` }" />

            <!-- 自定义范围 -->
            <div class="p-2.5">
              <div class="text-[9px] mb-1.5 font-medium"
                   :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.45)' }">
                自定义范围
              </div>
              <div class="flex gap-1.5 items-center mb-1.5">
                <span class="text-[10px] w-5 shrink-0"
                      :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">从</span>
                <input
                  type="datetime-local"
                  v-model="customFrom"
                  class="flex-1 px-1.5 py-1 rounded text-[10px] outline-none"
                  :style="{
                    background: inputBg,
                    border: `1px solid ${dropdownBorder}`,
                    color: isDark ? 'rgba(255,255,255,0.8)' : 'rgba(0,0,0,0.8)',
                    colorScheme: isDark ? 'dark' : 'light',
                  }"
                />
              </div>
              <div class="flex gap-1.5 items-center mb-2">
                <span class="text-[10px] w-5 shrink-0"
                      :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">至</span>
                <input
                  type="datetime-local"
                  v-model="customTo"
                  class="flex-1 px-1.5 py-1 rounded text-[10px] outline-none"
                  :style="{
                    background: inputBg,
                    border: `1px solid ${dropdownBorder}`,
                    color: isDark ? 'rgba(255,255,255,0.8)' : 'rgba(0,0,0,0.8)',
                    colorScheme: isDark ? 'dark' : 'light',
                  }"
                />
              </div>
              <button
                class="w-full py-1 rounded text-[10px] cursor-pointer font-medium"
                style="background: rgba(59,130,246,0.15); color: #3b82f6; border: 1px solid rgba(59,130,246,0.3);"
                @click="applyCustomRange"
              >应用时间范围</button>
            </div>

            <!-- 分隔线 -->
            <div :style="{ borderTop: `1px solid ${dropdownBorder}` }" />

            <!-- 自动刷新间隔 -->
            <div class="p-2.5 flex items-center justify-between">
              <span class="text-[9px] font-medium"
                    :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.45)' }">
                自动刷新
              </span>
              <div class="flex gap-1">
                <button
                  v-for="(ri, i) in REFRESH_INTERVALS" :key="ri.label"
                  class="px-1.5 py-0.5 rounded text-[9px] cursor-pointer"
                  :style="{
                    background: refreshIntervalIdx === i ? 'rgba(59,130,246,0.15)' : 'transparent',
                    color: refreshIntervalIdx === i ? '#3b82f6' : (isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)'),
                    border: `1px solid ${refreshIntervalIdx === i ? 'rgba(59,130,246,0.3)' : 'transparent'}`,
                  }"
                  @click="refreshIntervalIdx = i"
                >{{ ri.label }}</button>
              </div>
            </div>
          </div>
        </div>

        <!-- 刷新 -->
        <button
          class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] cursor-pointer"
          :style="{
            color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)',
            background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
            border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
          }"
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

      <!-- ── 图表区域 ── -->
      <div v-else class="grid grid-cols-2 gap-3">
        <!-- 行1: CPU | 内存 -->

        <!-- CPU 图表 -->
        <div v-if="cpuOption" class="rounded-lg p-1 relative" :style="{ background: panelBg }">
          <!-- View 按鈕 -->
          <button
            class="absolute top-1.5 right-1.5 z-10 px-1.5 py-0.5 rounded text-[9px] font-medium opacity-50 hover:opacity-100 transition-opacity"
            :style="{ background: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)', color: isDark ? '#fff' : '#333' }"
            @click="openView('cpu')"
          >□ View</button>
          <v-chart
            ref="cpuChartRef"
            :option="cpuOption"
            :init-options="{ renderer: 'canvas' }"
            style="height: 180px"
            autoresize
            @dblclick="handleDblClick('cpu')"
          />
          <!-- 底部统计行 -->
          <div class="flex items-center justify-end gap-x-1.5 gap-y-0 px-2 pb-1 text-[11px] font-mono">
            <span class="mr-1.5" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">&#9632; {{ selectedService }}</span>
            <span :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.38)' }">min</span>
            <span style="color: #4ade80" class="font-semibold">{{ formatCpuValue(cpuStats.min) }}</span>
            <span class="ml-1" :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.38)' }">max</span>
            <span style="color: #f87171" class="font-semibold">{{ formatCpuValue(cpuStats.max) }}</span>
            <span class="ml-1" :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.38)' }">avg</span>
            <span style="color: #60a5fa" class="font-semibold">{{ formatCpuValue(cpuStats.avg) }}</span>
            <span class="ml-1" :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.38)' }">cur</span>
            <span style="color: #fbbf24" class="font-semibold">{{ formatCpuValue(cpuStats.current) }}</span>
          </div>
        </div>
        <!-- CPU 无数据占位 -->
        <div v-else class="rounded-lg flex items-center justify-center" style="height: 210px" :style="{ background: panelBg }">
          <span class="text-[11px]" :style="{ color: isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.3)' }">无 CPU 数据</span>
        </div>

        <!-- 内存图表 -->
        <div v-if="memOption" class="rounded-lg p-1 relative" :style="{ background: panelBg }">
          <!-- View 按鈕 -->
          <button
            class="absolute top-1.5 right-1.5 z-10 px-1.5 py-0.5 rounded text-[9px] font-medium opacity-50 hover:opacity-100 transition-opacity"
            :style="{ background: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)', color: isDark ? '#fff' : '#333' }"
            @click="openView('mem')"
          >□ View</button>
          <v-chart
            ref="memChartRef"
            :option="memOption"
            :init-options="{ renderer: 'canvas' }"
            style="height: 180px"
            autoresize
            @dblclick="handleDblClick('mem')"
          />
          <!-- 底部统计行 -->
          <div class="flex items-center justify-end gap-x-1.5 gap-y-0 px-2 pb-1 text-[11px] font-mono">
            <span class="mr-1.5" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">&#9632; {{ selectedService }}</span>
            <span :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.38)' }">min</span>
            <span style="color: #4ade80" class="font-semibold">{{ formatMemValue(memStats.min) }}</span>
            <span class="ml-1" :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.38)' }">max</span>
            <span style="color: #f87171" class="font-semibold">{{ formatMemValue(memStats.max) }}</span>
            <span class="ml-1" :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.38)' }">avg</span>
            <span style="color: #60a5fa" class="font-semibold">{{ formatMemValue(memStats.avg) }}</span>
            <span class="ml-1" :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.38)' }">cur</span>
            <span style="color: #fbbf24" class="font-semibold">{{ formatMemValue(memStats.current) }}</span>
          </div>
        </div>
        <!-- 内存无数据占位 -->
        <div v-else class="rounded-lg flex items-center justify-center" style="height: 210px" :style="{ background: panelBg }">
          <span class="text-[11px]" :style="{ color: isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.3)' }">无内存数据</span>
        </div>

        <!-- 行2: Pod CPU | Pod 内存 -->

        <!-- Pod CPU 图表 -->
        <div v-if="cpuByPodOption" class="rounded-lg p-1 relative" :style="{ background: panelBg }">
          <!-- View 按鈕 -->
          <button
            class="absolute top-1.5 right-1.5 z-10 px-1.5 py-0.5 rounded text-[9px] font-medium opacity-50 hover:opacity-100 transition-opacity"
            :style="{ background: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)', color: isDark ? '#fff' : '#333' }"
            @click="openView('podCpu')"
          >□ View</button>
          <v-chart
            ref="cpuByPodChartRef"
            :option="cpuByPodOption"
            :init-options="{ renderer: 'canvas' }"
            style="height: 180px"
            autoresize
          />
          <!-- Pod CPU 统计表（Grafana 风格行格式） -->
          <div v-if="cpuPodStats.length" class="px-2 pb-1.5">
            <!-- 表头 -->
            <div class="flex text-[9px] font-mono mb-0.5" :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.38)' }">
              <span class="flex-1 min-w-0"></span>
              <span class="w-16 text-right">max</span>
              <span class="w-16 text-right">current</span>
            </div>
            <!-- 每个 Pod 一行 -->
            <div
              v-for="pod in cpuPodStats"
              :key="pod.name"
              class="flex items-center text-[9px] font-mono cursor-pointer rounded px-0.5"
              :style="{
                opacity: activeCpuPod && activeCpuPod !== pod.name ? 0.4 : 1,
                background: activeCpuPod === pod.name ? (isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)') : 'transparent',
              }"
              @click="clickCpuPod(pod.name)"
            >
              <span class="inline-block w-2 h-2 rounded-full flex-shrink-0 mr-1" :style="{ background: pod.color }" />
              <span class="flex-1 min-w-0 truncate" :title="pod.name" :style="{ color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)' }">{{ pod.name }}</span>
              <span class="w-16 text-right font-semibold" :style="{ color: pod.color }">{{ formatCpuValue(pod.max) }}</span>
              <span class="w-16 text-right font-semibold" style="color: #fbbf24">{{ formatCpuValue(pod.current) }}</span>
            </div>
          </div>
        </div>
        <!-- Pod CPU 无数据占位 -->
        <div v-else class="rounded-lg flex items-center justify-center" style="height: 210px" :style="{ background: panelBg }">
          <span class="text-[11px]" :style="{ color: isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.3)' }">无 Pod CPU 数据</span>
        </div>

        <!-- Pod 内存图表 -->
        <div v-if="memByPodOption" class="rounded-lg p-1 relative" :style="{ background: panelBg }">
          <!-- View 按鈕 -->
          <button
            class="absolute top-1.5 right-1.5 z-10 px-1.5 py-0.5 rounded text-[9px] font-medium opacity-50 hover:opacity-100 transition-opacity"
            :style="{ background: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)', color: isDark ? '#fff' : '#333' }"
            @click="openView('podMem')"
          >□ View</button>
          <v-chart
            ref="memByPodChartRef"
            :option="memByPodOption"
            :init-options="{ renderer: 'canvas' }"
            style="height: 180px"
            autoresize
          />
          <!-- Pod 内存统计表（Grafana 风格行格式） -->
          <div v-if="memPodStats.length" class="px-2 pb-1.5">
            <!-- 表头 -->
            <div class="flex text-[9px] font-mono mb-0.5" :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.38)' }">
              <span class="flex-1 min-w-0"></span>
              <span class="w-16 text-right">max</span>
              <span class="w-16 text-right">current</span>
            </div>
            <!-- 每个 Pod 一行 -->
            <div
              v-for="pod in memPodStats"
              :key="pod.name"
              class="flex items-center text-[9px] font-mono cursor-pointer rounded px-0.5"
              :style="{
                opacity: activeMemPod && activeMemPod !== pod.name ? 0.4 : 1,
                background: activeMemPod === pod.name ? (isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)') : 'transparent',
              }"
              @click="clickMemPod(pod.name)"
            >
              <span class="inline-block w-2 h-2 rounded-full flex-shrink-0 mr-1" :style="{ background: pod.color }" />
              <span class="flex-1 min-w-0 truncate" :title="pod.name" :style="{ color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)' }">{{ pod.name }}</span>
              <span class="w-16 text-right font-semibold" :style="{ color: pod.color }">{{ formatMemValue(pod.max) }}</span>
              <span class="w-16 text-right font-semibold" style="color: #fbbf24">{{ formatMemValue(pod.current) }}</span>
            </div>
          </div>
        </div>
        <!-- Pod 内存无数据占位 -->
        <div v-else class="rounded-lg flex items-center justify-center" style="height: 210px" :style="{ background: panelBg }">
          <span class="text-[11px]" :style="{ color: isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.3)' }">无 Pod 内存数据</span>
        </div>

        <!-- 行3: 磁盘 I/O | 网络流量 -->

        <!-- 磁盘 I/O 图表 -->
        <div v-if="diskOption" class="rounded-lg p-1 relative" :style="{ background: panelBg }">
          <!-- View 按鈕 -->
          <button
            class="absolute top-1.5 right-1.5 z-10 px-1.5 py-0.5 rounded text-[9px] font-medium opacity-50 hover:opacity-100 transition-opacity"
            :style="{ background: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)', color: isDark ? '#fff' : '#333' }"
            @click="openView('disk')"
          >□ View</button>
          <v-chart
            ref="diskChartRef"
            :option="diskOption"
            :init-options="{ renderer: 'canvas' }"
            style="height: 180px"
            autoresize
            @dblclick="handleDblClick('disk')"
          />
          <!-- 底部统计行 -->
          <div class="flex items-center justify-end gap-x-1.5 gap-y-0 px-2 pb-1 text-[11px] font-mono">
            <span class="mr-1.5" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">&#9632; {{ selectedService }}</span>
            <span :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.38)' }">读</span>
            <span style="color: #4ade80" class="font-semibold">{{ formatNetDiskValue(diskReadStats.avg) }}</span>
            <span class="ml-1" :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.38)' }">写</span>
            <span style="color: #f87171" class="font-semibold">{{ formatNetDiskValue(diskWriteStats.avg) }}</span>
            <span class="ml-1" :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.38)' }">读 max</span>
            <span style="color: #fbbf24" class="font-semibold">{{ formatNetDiskValue(diskReadStats.max) }}</span>
          </div>
        </div>
        <!-- 磁盘无数据占位 -->
        <div v-else class="rounded-lg flex items-center justify-center" style="height: 210px" :style="{ background: panelBg }">
          <span class="text-[11px]" :style="{ color: isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.3)' }">无磁盘数据</span>
        </div>

        <!-- 网络流量图表 -->
        <div v-if="networkOption" class="rounded-lg p-1 relative" :style="{ background: panelBg }">
          <!-- View 按鈕 -->
          <button
            class="absolute top-1.5 right-1.5 z-10 px-1.5 py-0.5 rounded text-[9px] font-medium opacity-50 hover:opacity-100 transition-opacity"
            :style="{ background: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)', color: isDark ? '#fff' : '#333' }"
            @click="openView('network')"
          >□ View</button>
          <v-chart
            ref="networkChartRef"
            :option="networkOption"
            :init-options="{ renderer: 'canvas' }"
            style="height: 180px"
            autoresize
            @dblclick="handleDblClick('network')"
          />
          <!-- 底部统计行 -->
          <div class="flex items-center justify-end gap-x-1.5 gap-y-0 px-2 pb-1 text-[11px] font-mono">
            <span class="mr-1.5" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">&#9632; {{ selectedService }}</span>
            <span :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.38)' }">RX avg</span>
            <span style="color: #4ade80" class="font-semibold">{{ formatNetDiskValue(netRxStats.avg) }}</span>
            <span class="ml-1" :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.38)' }">TX avg</span>
            <span style="color: #f87171" class="font-semibold">{{ formatNetDiskValue(netTxStats.avg) }}</span>
            <span class="ml-1" :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.38)' }">RX max</span>
            <span style="color: #fbbf24" class="font-semibold">{{ formatNetDiskValue(netRxStats.max) }}</span>
          </div>
        </div>
        <!-- 网络无数据占位 -->
        <div v-else class="rounded-lg flex items-center justify-center" style="height: 210px" :style="{ background: panelBg }">
          <span class="text-[11px]" :style="{ color: isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.3)' }">无网络数据</span>
        </div>
      </div>

      <!-- 全屏 View 弹窗 -->
      <teleport to="body">
        <div
          v-if="viewPanel"
          class="fixed inset-0 z-50 flex items-center justify-center"
          style="background: rgba(0,0,0,0.75); backdrop-filter: blur(4px);"
          @click.self="closeView()"
        >
          <div
            class="relative rounded-xl overflow-hidden"
            :style="{ background: isDark ? '#1a1a2e' : '#ffffff', width: '90vw', maxWidth: '1200px', padding: '16px' }"
          >
            <!-- 弹窗标题与关闭 -->
            <div class="flex items-center justify-between mb-3">
              <span class="text-[13px] font-medium" :style="{ color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.8)' }">
                {{ VIEW_TITLES[viewPanel] }} — {{ selectedService }}
              </span>
              <button
                class="text-[11px] px-2 py-1 rounded opacity-60 hover:opacity-100 transition-opacity"
                :style="{ background: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)', color: isDark ? '#fff' : '#333' }"
                @click="closeView()"
              >✕ 关闭</button>
            </div>
            <!-- 全屏图表（非表格类型） -->
            <v-chart
              v-if="viewOption && viewPanel !== 'podDetail'"
              :option="viewOption"
              :init-options="{ renderer: 'canvas' }"
              style="height: 65vh; width: 100%;"
              autoresize
            />
            <!-- 全屏 Pod 资源明细表格 -->
            <div v-else-if="viewPanel === 'podDetail' && fbData" class="overflow-x-auto overflow-y-auto" style="max-height: 65vh">
              <table class="w-full text-[10px] font-mono" style="border-collapse: collapse">
                <thead class="sticky top-0 z-10" :style="{ background: isDark ? '#1a1a2e' : '#ffffff' }">
                  <tr :style="{ borderBottom: `1px solid ${isDark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.1)'}` }">
                    <th class="px-3 py-2 text-center font-medium" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">命名空间</th>
                    <th class="px-3 py-2 text-center font-medium" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">Pod 名称</th>
                    <th class="px-3 py-2 text-center font-medium" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">CPU %</th>
                    <th class="px-3 py-2 text-center font-medium" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">CPU需求</th>
                    <th class="px-3 py-2 text-center font-medium" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">CPU限制</th>
                    <th class="px-3 py-2 text-center font-medium" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">内存需求</th>
                    <th class="px-3 py-2 text-center font-medium" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">内存限制</th>
                    <th class="px-3 py-2 text-center font-medium" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">磁盘</th>
                    <th class="px-3 py-2 text-center font-medium" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">重启</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(pod, idx) in fbData.pods.filter(p => cpuPodStats.some(s => s.name === p.pod))"
                    :key="pod.pod"
                    :style="{
                      background: idx % 2 === 0 ? 'transparent' : (isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.015)'),
                      borderBottom: `1px solid ${isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)'}`,
                    }"
                  >
                    <td class="px-3 py-1.5 text-center" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">{{ pod.namespace || '-' }}</td>
                    <td class="px-3 py-1.5 text-center whitespace-nowrap" :title="pod.pod" :style="{ color: isDark ? 'rgba(255,255,255,0.8)' : 'rgba(0,0,0,0.8)' }">{{ pod.pod }}</td>
                    <td class="px-3 py-1.5 text-center" :style="{ color: pod.cpu_pct != null && pod.cpu_pct > 80 ? '#f87171' : '#60a5fa' }">{{ fmtCpuPct(pod.cpu_pct) }}</td>
                    <td class="px-3 py-1.5 text-center" style="color: #94a3b8">{{ fmtCpuCores(pod.cpu_request_m) }}</td>
                    <td class="px-3 py-1.5 text-center" style="color: #94a3b8">{{ fmtCpuCores(pod.cpu_limit_m) }}</td>
                    <td class="px-3 py-1.5 text-center" style="color: #94a3b8">{{ fmtMemGiB(pod.mem_request_mb) }}</td>
                    <td class="px-3 py-1.5 text-center" style="color: #94a3b8">{{ fmtMemGiB(pod.mem_limit_mb) }}</td>
                    <td class="px-3 py-1.5 text-center" style="color: #f59e0b">{{ fmtDiskUsage(pod.disk_usage_bytes) }}</td>
                    <td class="px-3 py-1.5 text-center" :style="{ color: pod.restarts != null && pod.restarts > 0 ? '#f87171' : (isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)') }">{{ pod.restarts != null ? Math.round(pod.restarts) : '-' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </teleport>

      <!-- Pod 资源明细 -->
      <div class="mt-4">
        <!-- 标题居中 -->
        <div class="flex items-center justify-center mb-2">
          <span class="text-[12px] font-medium" :style="{ color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)' }">
            Pod 资源明细
          </span>
        </div>
        <!-- 按钮组 -->
        <div class="flex items-center justify-end gap-2 mb-3">
          <span v-if="fbLoadedAt" class="text-[9px]" :style="{ color: isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.3)' }">
            {{ new Date(fbLoadedAt).toLocaleTimeString() }}
          </span>
          <!-- View 全屏按钮 -->
          <button
            class="px-1.5 py-0.5 rounded text-[9px] font-medium opacity-60 hover:opacity-100 transition-opacity"
            :style="{ background: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)', color: isDark ? '#fff' : '#333' }"
            @click="openView('podDetail')"
          >□ View</button>
          <button
            class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] cursor-pointer"
            :style="{
              color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)',
              background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
              border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
            }"
            :disabled="fbLoading"
            @click="fetchFluentBit"
          >
            <RefreshCw :size="10" :class="{ 'animate-spin': fbLoading }" />
            刷新
          </button>
        </div>

        <!-- 错误 -->
        <p v-if="fbError" class="text-[11px] text-red-500 flex items-center gap-1 mb-2">
          <AlertCircle :size="11" /> {{ fbError }}
        </p>

        <!-- 加载中 -->
        <div v-if="fbLoading && !fbData" class="flex items-center gap-2 py-4 justify-center"
             :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">
          <Loader :size="12" class="animate-spin" />
          <span class="text-[11px]">加载中…</span>
        </div>

        <!-- 无数据 -->
        <div v-else-if="!fbData || !fbData.pods.filter(p => cpuPodStats.some(s => s.name === p.pod)).length" class="py-4 text-center text-[11px]"
             :style="{ color: isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.3)' }">
          未找到 {{ selectedService }} 的 Pod 资源数据
        </div>

        <!-- 表格 -->
        <div v-else class="overflow-x-auto rounded-lg" :style="{ background: panelBg }">
          <table class="w-full text-[10px] font-mono" style="border-collapse: collapse">
            <thead>
              <tr :style="{ borderBottom: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}` }">
                <th class="px-2 py-1.5 text-center font-medium" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">命名空间</th>
                <th class="px-2 py-1.5 text-center font-medium" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">Pod 名称</th>
                <th class="px-2 py-1.5 text-center font-medium" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">CPU %</th>
                <th class="px-2 py-1.5 text-center font-medium" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">CPU需求</th>
                <th class="px-2 py-1.5 text-center font-medium" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">CPU限制</th>
                <th class="px-2 py-1.5 text-center font-medium" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">内存需求</th>
                <th class="px-2 py-1.5 text-center font-medium" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">内存限制</th>
                <th class="px-2 py-1.5 text-center font-medium" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">磁盘</th>
                <th class="px-2 py-1.5 text-center font-medium" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">重启</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(pod, idx) in fbData.pods.filter(p => cpuPodStats.some(s => s.name === p.pod))"
                :key="pod.pod"
                :style="{
                  background: idx % 2 === 0 ? 'transparent' : (isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.015)'),
                  borderBottom: `1px solid ${isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)'}`,
                }"
              >
                <td class="px-2 py-1.5 text-center" :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">{{ pod.namespace || '-' }}</td>
                <td class="px-2 py-1.5 text-center whitespace-nowrap" :title="pod.pod" :style="{ color: isDark ? 'rgba(255,255,255,0.75)' : 'rgba(0,0,0,0.75)' }">{{ pod.pod }}</td>
                <td class="px-2 py-1.5 text-center" :style="{ color: pod.cpu_pct != null && pod.cpu_pct > 80 ? '#f87171' : '#60a5fa' }">{{ fmtCpuPct(pod.cpu_pct) }}</td>
                <td class="px-2 py-1.5 text-center" style="color: #94a3b8">{{ fmtCpuCores(pod.cpu_request_m) }}</td>
                <td class="px-2 py-1.5 text-center" style="color: #94a3b8">{{ fmtCpuCores(pod.cpu_limit_m) }}</td>
                <td class="px-2 py-1.5 text-center" style="color: #94a3b8">{{ fmtMemGiB(pod.mem_request_mb) }}</td>
                <td class="px-2 py-1.5 text-center" style="color: #94a3b8">{{ fmtMemGiB(pod.mem_limit_mb) }}</td>
                <td class="px-2 py-1.5 text-center" style="color: #f59e0b">{{ fmtDiskUsage(pod.disk_usage_bytes) }}</td>
                <td class="px-2 py-1.5 text-center" :style="{ color: pod.restarts != null && pod.restarts > 0 ? '#f87171' : (isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)') }">{{ pod.restarts != null ? Math.round(pod.restarts) : '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 底部提示 -->
        <div class="mt-2 space-y-1">
          <!-- 操作提示 -->
          <div class="text-center text-[9px]"
               :style="{ color: isDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.3)' }">
            滚轮缩放 · 拖拽平移 · 双击重置或扩展范围
          </div>
          <!-- 数据更新时间 -->
          <p v-if="fbLoadedAt" class="text-[10px] text-center"
             :style="{ color: isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.35)' }">
            数据更新于 {{ new Date(fbLoadedAt).toLocaleTimeString() }}
            <template v-if="isRunActive"> · 运行中每 30s 自动刷新</template>
            <template v-else-if="refreshMs > 0"> · 每 {{ REFRESH_INTERVALS[refreshIntervalIdx].label }} 自动刷新</template>
          </p>
        </div>
      </div>
    </template>
  </div>
</template>
