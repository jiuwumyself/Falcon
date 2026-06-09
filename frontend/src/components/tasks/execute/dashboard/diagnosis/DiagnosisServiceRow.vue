<script setup lang="ts">
// 一个被压测服务的诊断行：折叠=汇总(CPU/MEM/QPS/P95/ERR + 趋势条)，展开=详情(拓扑+Pod时序+Pinpoint)。
import { computed, ref, watch } from 'vue'
import { ChevronRight, Server } from 'lucide-vue-next'
import { runsApi, tasksApi, prometheusSourcesApi } from '@/lib/api'
import { usePrometheusMetrics } from '@/composables/usePrometheusMetrics'
import ServerMapPanel from '../trace/ServerMapPanel.vue'
import PodTimeseriesPanel from './PodTimeseriesPanel.vue'
import PinpointPanels from './PinpointPanels.vue'
import type { DiagnosisResponse, ServerMapResponse, Task, TaskRun } from '@/types/task'

const props = defineProps<{
  task: Task
  run: TaskRun | null
  service: string
  expanded: boolean
  isTerminal: boolean
  startSec: number        // 时间窗（父级时间选择器决定）
  endSec: number
  range: string           // 时间窗 id（'run'/'5m'… 切换才重拉详情，滑动只刷新汇总）
  isDark: boolean
}>()
const emit = defineEmits<{ (e: 'toggle'): void; (e: 'cpu', service: string, cpu: number | null): void }>()
const dd = (l: string, dk: string) => (props.isDark ? dk : l)

const startSec = computed(() => props.startSec)
const endSec = computed(() => props.endSec)
const winMs = computed(() => ({ from: props.startSec * 1000, to: props.endSec * 1000 }))
// 「本次压测」且有 run → 走 run 级（终态快照/run 窗口）；否则（近 N 分预设 / 没 run）→ task 级 + 时间窗，不压测也能看
const useRun = computed(() => props.range === 'run' && !!props.run?.run_id)

// ── 汇总（折叠行）──
const cpuAvg = ref<number | null>(null)
const memAvg = ref<number | null>(null)
const sparkData = ref<number[]>([])
const qps = ref<number | null>(null)
const errRate = ref<number | null>(null)
const respMs = ref<number | null>(null)   // 每服务平均响应时间（Pinpoint，非 run 级共用值）
const podCount = ref(0)
const sumLoading = ref(false)

function avgOf(series: { ts: number; value: number }[] | undefined): number | null {
  if (!series?.length) return null
  return series.reduce((a, b) => a + b.value, 0) / series.length
}

async function loadSummary() {
  const sid = props.task.prometheus_source
  if (!props.service || !(endSec.value > startSec.value)) return
  sumLoading.value = true
  // Prometheus：CPU/MEM 整体（task/service/window，无需 run）
  if (sid) {
    prometheusSourcesApi.metrics(sid, {
      service: props.service, start: startSec.value, end: endSec.value,
      step: `${Math.max(15, Math.floor((endSec.value - startSec.value) / 120))}s`,
      metrics: 'cpu_usage,memory_usage',
    }).then((m) => {
      cpuAvg.value = avgOf(m.cpu_usage?.data)
      memAvg.value = avgOf(m.memory_usage?.data)
      sparkData.value = (m.cpu_usage?.data || []).map((d) => d.value)
      emit('cpu', props.service, cpuAvg.value)   // 给父级排序用（CPU 高的排前面）
    }).catch(() => { emit('cpu', props.service, null) })
  } else { emit('cpu', props.service, null) }
  // Pinpoint brief（QPS/ERR/响应/Pod）：本次压测走 run 级，预设/无 run 走 task 级
  const briefP = useRun.value
    ? runsApi.pinpointDiagnosis(props.run!.run_id, props.service, true)
    : tasksApi.serviceDiagnosis(props.task.id, props.service, true, winMs.value)
  briefP.then((r) => {
    if (r.transactions) {
      qps.value = r.transactions.tps
      errRate.value = r.transactions.error_rate
      respMs.value = r.transactions.avg_ms
    }
    if (r.pods?.length) podCount.value = r.pods.length
  }).catch(() => {}).finally(() => { sumLoading.value = false })
}

// ── 详情（展开）──
const detail = ref<DiagnosisResponse | null>(null)
const serverMap = ref<ServerMapResponse | null>(null)
const detailLoaded = ref(false)
const detailLoading = ref(false)
const mapLoading = ref(false)
const { data: promData, loading: promLoading, load: loadProm, loadRunSnapshot } = usePrometheusMetrics()
const hasServerMap = computed(() => !!serverMap.value?.enabled && serverMap.value.nodes.length > 0)

async function loadDetail() {
  if (!props.service) return
  detailLoaded.value = true
  // Pod 时序：本次压测+终态读 run 级快照(秒开)；否则实时拉(task/service/window，无需 run)
  if (useRun.value && props.isTerminal) {
    loadRunSnapshot(props.run!.run_id, props.service)
  } else {
    loadProm(props.task.prometheus_source, props.service, startSec.value, endSec.value)
  }
  // Pinpoint 详情 + 拓扑：本次压测走 run 级，预设/无 run 走 task 级
  detailLoading.value = true
  const dP = useRun.value
    ? runsApi.pinpointDiagnosis(props.run!.run_id, props.service)
    : tasksApi.serviceDiagnosis(props.task.id, props.service, false, winMs.value)
  dP.then((r) => { detail.value = r }).catch(() => { detail.value = null }).finally(() => { detailLoading.value = false })
  mapLoading.value = true
  const mP = useRun.value
    ? runsApi.pinpointServerMap(props.run!.run_id, { service: props.service, inbound: 2, outbound: 2 })
    : tasksApi.serviceServermap(props.task.id, props.service, winMs.value)
  mP.then((r) => { serverMap.value = r }).catch(() => { serverMap.value = null }).finally(() => { mapLoading.value = false })
}

watch(() => props.expanded, (v) => { if (v && !detailLoaded.value) loadDetail() })
// 实体变化（run/服务/终态）→ 完全重置重载
watch([() => props.run?.run_id, () => props.service, () => props.isTerminal], () => {
  detailLoaded.value = false; detail.value = null; serverMap.value = null
  cpuAvg.value = memAvg.value = qps.value = errRate.value = respMs.value = null
  loadSummary()
  if (props.expanded) loadDetail()
}, { immediate: true })
// 切换时间窗（下拉）→ 原地重拉详情（拓扑/Pinpoint/Pod时序），保留旧数据不闪
watch(() => props.range, () => {
  loadSummary()
  if (props.expanded && detailLoaded.value) loadDetail()
})
// 时间窗滑动（近 N 分每 10s 自动跟进）→ 只刷新轻量汇总，不重拉慢的详情
watch([() => props.startSec, () => props.endSec], () => { loadSummary() })

// 健康点颜色：错误率/CPU 越高越红
const dotColor = computed(() => {
  const e = errRate.value ?? 0, c = cpuAvg.value ?? 0
  if (e >= 5 || c >= 90) return '#ef4444'
  if (e >= 1 || c >= 70) return '#f59e0b'
  return '#10b981'
})
const fmtPct = (v: number | null) => (v == null ? '—' : v.toFixed(0) + '%')
const fmtNum = (v: number | null) => (v == null ? '—' : (v >= 1000 ? (v / 1000).toFixed(1) + 'k' : v.toFixed(v < 10 ? 1 : 0)))
const cpuColor = computed(() => (cpuAvg.value ?? 0) >= 90 ? '#ef4444' : (cpuAvg.value ?? 0) >= 70 ? '#f59e0b' : dd('#1a1a2e', '#fff'))
const memColor = computed(() => (memAvg.value ?? 0) >= 85 ? '#ef4444' : (memAvg.value ?? 0) >= 70 ? '#f59e0b' : dd('#1a1a2e', '#fff'))

// 迷你 sparkline path
const sparkPath = computed(() => {
  const d = sparkData.value
  if (d.length < 2) return ''
  const mn = Math.min(...d), mx = Math.max(...d), rng = mx - mn || 1
  const W = 120, H = 28
  return d.map((v, i) => `${i === 0 ? 'M' : 'L'}${(i / (d.length - 1) * W).toFixed(1)},${(H - (v - mn) / rng * H).toFixed(1)}`).join(' ')
})
</script>

<template>
  <div class="rounded-xl overflow-hidden" :style="{
    background: dd('rgba(255,255,255,0.5)', 'rgba(255,255,255,0.02)'),
    border: `1px solid ${expanded ? dd('rgba(0,0,0,0.12)', 'rgba(255,255,255,0.12)') : dd('rgba(0,0,0,0.06)', 'rgba(255,255,255,0.06)')}`,
  }">
    <!-- 折叠汇总行 -->
    <div class="flex items-center gap-3 px-3.5 py-2.5 cursor-pointer select-none" @click="emit('toggle')">
      <ChevronRight :size="15" class="transition-transform flex-shrink-0"
                    :style="{ transform: expanded ? 'rotate(90deg)' : 'none', color: dd('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.45)') }" />
      <span class="w-2 h-2 rounded-full flex-shrink-0" :style="{ background: dotColor }" />
      <Server :size="14" :color="dd('rgba(0,0,0,0.5)', 'rgba(255,255,255,0.5)')" class="flex-shrink-0" />
      <div class="min-w-0">
        <p class="text-[13px] font-medium m-0 truncate" :style="{ color: dotColor === '#ef4444' ? '#ef4444' : dd('#1a1a2e', '#fff') }">{{ service }}</p>
        <p class="text-[10px] m-0" :style="{ color: dd('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">{{ podCount || '—' }} PODS</p>
      </div>
      <span class="flex-1" />
      <!-- 指标列（固定宽，跨行对齐）-->
      <div class="hidden sm:flex items-start tabular-nums flex-shrink-0">
        <div class="w-14 text-right"><p class="text-[9px] m-0" :style="{ color: dd('rgba(0,0,0,0.35)', 'rgba(255,255,255,0.35)') }">CPU</p><p class="text-[13px] font-medium m-0" :style="{ color: cpuColor }">{{ fmtPct(cpuAvg) }}</p></div>
        <div class="w-14 text-right"><p class="text-[9px] m-0" :style="{ color: dd('rgba(0,0,0,0.35)', 'rgba(255,255,255,0.35)') }">MEM</p><p class="text-[13px] font-medium m-0" :style="{ color: memColor }">{{ fmtPct(memAvg) }}</p></div>
        <div class="w-14 text-right"><p class="text-[9px] m-0" :style="{ color: dd('rgba(0,0,0,0.35)', 'rgba(255,255,255,0.35)') }">QPS</p><p class="text-[13px] font-medium m-0" :style="{ color: dd('#1a1a2e', '#fff') }">{{ fmtNum(qps) }}</p></div>
        <div class="w-16 text-right"><p class="text-[9px] m-0" :style="{ color: dd('rgba(0,0,0,0.35)', 'rgba(255,255,255,0.35)') }">响应</p><p class="text-[13px] font-medium m-0" :style="{ color: dd('#1a1a2e', '#fff') }">{{ respMs == null ? '—' : respMs + 'ms' }}</p></div>
        <div class="w-14 text-right"><p class="text-[9px] m-0" :style="{ color: dd('rgba(0,0,0,0.35)', 'rgba(255,255,255,0.35)') }">ERR%</p><p class="text-[13px] font-medium m-0" :style="{ color: (errRate ?? 0) > 0 ? '#ef4444' : '#10b981' }">{{ errRate == null ? '—' : errRate.toFixed(2) }}</p></div>
      </div>
      <svg viewBox="0 0 120 28" class="w-[110px] h-[28px] flex-shrink-0 ml-3 hidden md:block">
        <path v-if="sparkPath" :d="sparkPath" fill="none" :stroke="dotColor" stroke-width="1.4" />
      </svg>
    </div>

    <!-- 展开详情：自身内部滚动（数据下滑只在单个服务里，不整体下滑） -->
    <div v-if="expanded" class="px-3.5 pb-3.5 flex flex-col gap-3 border-t max-h-[64vh] overflow-y-auto"
         :style="{ borderColor: dd('rgba(0,0,0,0.06)', 'rgba(255,255,255,0.06)') }">
      <!-- 拓扑 -->
      <div class="pt-3">
        <ServerMapPanel v-if="hasServerMap" :data="serverMap!" :focus-name="detail?.pinpoint_app || service" :is-dark="isDark" />
        <p v-else-if="!mapLoading" class="text-[11px] py-3 text-center rounded-lg"
           :style="{ color: dd('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.45)'), background: dd('rgba(0,0,0,0.02)', 'rgba(255,255,255,0.02)') }">
          该服务此时段无 Pinpoint 拓扑
        </p>
        <p v-else class="text-[11px] py-3 text-center" :style="{ color: dd('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">加载拓扑…</p>
      </div>
      <!-- Pod 时序 -->
      <PodTimeseriesPanel :data="promData" :loading="promLoading" :is-dark="isDark" />
      <!-- Pinpoint -->
      <PinpointPanels v-if="detail?.available" :data="detail" :run-id="run?.run_id || null" :is-dark="isDark" />
      <p v-else-if="!detailLoading && detailLoaded" class="text-[11px] py-3 text-center rounded-lg"
         :style="{ color: dd('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.45)'), background: dd('rgba(0,0,0,0.02)', 'rgba(255,255,255,0.02)') }">
        {{ detail?.reason || '该服务暂无 Pinpoint 数据' }}
      </p>
    </div>
  </div>
</template>
