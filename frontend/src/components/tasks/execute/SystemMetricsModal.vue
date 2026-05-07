<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { X, Cpu, Loader, AlertCircle } from 'lucide-vue-next'
import { ApiError, loadGeneratorsApi, type SystemMetrics } from '@/lib/api'
import type { LoadGenerator } from '@/types/task'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent, TitleComponent, TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([LineChart, GridComponent, TitleComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  lg: LoadGenerator | null      // null = 关闭
  isDark: boolean
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

const POLL_MS = 3000
const MAX_POINTS = 60     // 保留最近 3 分钟数据（60 × 3s）

const series = ref<{
  cpu: [number, number][]
  mem: [number, number][]
  netIn: [number, number][]
  netOut: [number, number][]
  diskRead: [number, number][]
  diskWrite: [number, number][]
}>({ cpu: [], mem: [], netIn: [], netOut: [], diskRead: [], diskWrite: [] })

const error = ref('')
const loading = ref(false)
let pollTimer: number | undefined

async function tick() {
  if (!props.lg) return
  loading.value = true
  try {
    const m: SystemMetrics = await loadGeneratorsApi.systemMetrics(props.lg.id)
    const ts = m.timestamp
    series.value = {
      cpu: pushPoint(series.value.cpu, [ts, m.cpu_pct]),
      mem: pushPoint(series.value.mem, [ts, m.mem_pct]),
      netIn: pushPoint(series.value.netIn, [ts, m.net_kbs_in]),
      netOut: pushPoint(series.value.netOut, [ts, m.net_kbs_out]),
      diskRead: pushPoint(series.value.diskRead, [ts, m.disk_iops_read]),
      diskWrite: pushPoint(series.value.diskWrite, [ts, m.disk_iops_write]),
    }
    error.value = ''
  } catch (e) {
    error.value = e instanceof ApiError ? e.humanMessage : String(e)
  } finally {
    loading.value = false
  }
}

function pushPoint(arr: [number, number][], p: [number, number]): [number, number][] {
  const next = [...arr, p]
  return next.length > MAX_POINTS ? next.slice(-MAX_POINTS) : next
}

function startPoll() {
  series.value = { cpu: [], mem: [], netIn: [], netOut: [], diskRead: [], diskWrite: [] }
  tick()
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = window.setInterval(tick, POLL_MS)
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = undefined
  }
}

watch(() => props.lg?.id, (id) => {
  if (id != null) startPoll()
  else stopPoll()
})

onMounted(() => { if (props.lg) startPoll() })
onBeforeUnmount(stopPoll)

const axisColor = computed(() => props.isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.5)')
const splitColor = computed(() => props.isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)')

function makeOption(title: string, color: string, ...lines: { name: string; data: [number, number][] }[]) {
  return {
    title: { text: title, left: 8, top: 4, textStyle: { fontSize: 11, color: axisColor.value } },
    grid: { top: 30, left: 36, right: 12, bottom: 22 },
    tooltip: { trigger: 'axis' },
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
    series: lines.map((l, i) => ({
      type: 'line', name: l.name, data: l.data, smooth: true, symbol: 'none',
      lineStyle: { width: 1.5, color: i === 0 ? color : '#a78bfa' },
      areaStyle: i === 0 ? { color, opacity: 0.18 } : undefined,
    })),
  }
}

const cpuOpt = computed(() => makeOption('CPU %', '#3b82f6', { name: 'CPU', data: series.value.cpu }))
const memOpt = computed(() => makeOption('内存 %', '#10b981', { name: 'Mem', data: series.value.mem }))
const netOpt = computed(() => makeOption('网络 KB/s', '#f59e0b',
  { name: 'In', data: series.value.netIn },
  { name: 'Out', data: series.value.netOut },
))
const diskOpt = computed(() => makeOption('磁盘 IOPS', '#ec4899',
  { name: 'Read', data: series.value.diskRead },
  { name: 'Write', data: series.value.diskWrite },
))
</script>

<template>
  <div
    v-if="lg"
    class="fixed inset-0 z-50 flex items-center justify-center"
    :style="{ background: 'rgba(0,0,0,0.6)' }"
    @click.self="emit('close')"
  >
    <div
      class="rounded-2xl p-4 w-[760px] max-w-[90vw] max-h-[85vh] overflow-y-auto"
      :style="{
        background: isDark ? '#0d0d12' : '#ffffff',
        border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
        boxShadow: '0 20px 60px rgba(0,0,0,0.4)',
      }"
    >
      <div class="flex items-center gap-2 mb-3">
        <Cpu :size="14" color="#3b82f6" />
        <span class="text-[14px]" :style="{ color: isDark ? '#fff' : '#1a1a2e' }">
          压力源系统指标
        </span>
        <span class="text-[11px]"
              :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.45)' }">
          {{ lg.pod_name }} · {{ lg.cpu_cores }} 核 / {{ lg.memory_gb }} GB · {{ lg.ip }}:{{ lg.port }}
        </span>
        <Loader v-if="loading" :size="11" class="ml-1 animate-spin"
                :color="isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)'" />
        <button
          class="ml-auto flex items-center justify-center w-6 h-6 rounded cursor-pointer hover:bg-black/10"
          @click="emit('close')"
        >
          <X :size="14" :color="isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.6)'" />
        </button>
      </div>

      <p v-if="error" class="text-[11px] text-red-500 flex items-center gap-1 mb-2">
        <AlertCircle :size="11" /> {{ error }}
      </p>

      <div class="grid grid-cols-2 gap-2.5">
        <div class="rounded-lg p-1"
             :style="{ background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)' }">
          <v-chart :option="cpuOpt" :init-options="{ renderer: 'canvas' }" style="height: 160px" autoresize />
        </div>
        <div class="rounded-lg p-1"
             :style="{ background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)' }">
          <v-chart :option="memOpt" :init-options="{ renderer: 'canvas' }" style="height: 160px" autoresize />
        </div>
        <div class="rounded-lg p-1"
             :style="{ background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)' }">
          <v-chart :option="netOpt" :init-options="{ renderer: 'canvas' }" style="height: 160px" autoresize />
        </div>
        <div class="rounded-lg p-1"
             :style="{ background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)' }">
          <v-chart :option="diskOpt" :init-options="{ renderer: 'canvas' }" style="height: 160px" autoresize />
        </div>
      </div>

      <p class="text-[10px] mt-3 text-center"
         :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.4)' }">
        每 3s 主控代理拉取 agent psutil；保留最近 3 分钟数据
      </p>
    </div>
  </div>
</template>
