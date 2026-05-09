<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { ErrorAggregateRow, RunMetrics, SamplerStat, TaskRun } from '@/types/task'
import { runsApi } from '@/lib/api'
import KpiBar from './KpiBar.vue'
import ErrorRateGauge from './ErrorRateGauge.vue'
import ErrorCountChart from './ErrorCountChart.vue'
import ConcurrencyChart from './ConcurrencyChart.vue'
import ThroughputPerVuChart from './ThroughputPerVuChart.vue'
import ConcurrencyRpsChart from './ConcurrencyRpsChart.vue'
import RpsChart from './RpsChart.vue'
import LatencyChart from './LatencyChart.vue'
import NetworkChart from './NetworkChart.vue'
import ErrorTransactionTable from './ErrorTransactionTable.vue'
import ErrorMessageTable from './ErrorMessageTable.vue'

const props = defineProps<{
  run: TaskRun | null
  metrics: RunMetrics | null
  isDark: boolean
}>()

const SAMPLER_POLL_MS = 5000
const ERROR_POLL_MS = 10000
const ERROR_LIMIT = 100   // aggregate 模式下 limit 控制聚合后行数（不是样本数），50-100 足够

const TERMINAL_STATUSES: TaskRun['status'][] = [
  'pre_check_failed', 'success', 'failed', 'timeout', 'cancelled',
]

const samplerStats = ref<SamplerStat[]>([])
const errorAggregates = ref<ErrorAggregateRow[]>([])

let samplerTimer: number | null = null
let errorTimer: number | null = null

const activeRunId = computed(() => props.run?.run_id || null)
const isTerminal = computed(
  () => !!props.run && TERMINAL_STATUSES.includes(props.run.status),
)

async function fetchSamplerStats() {
  const id = activeRunId.value
  if (!id) {
    samplerStats.value = []
    return
  }
  try {
    samplerStats.value = await runsApi.samplerStats(id)
  } catch {
    // 静默失败：运行刚开始 / sampler-stats 未就绪都会 404，不报红
  }
}

async function fetchErrorAggregates() {
  const id = activeRunId.value
  if (!id) {
    errorAggregates.value = []
    return
  }
  try {
    const res = await runsApi.errorAggregates(id, { limit: ERROR_LIMIT })
    errorAggregates.value = res.aggregates
  } catch {
    // 同上
  }
}

function startTimers() {
  stopTimers()
  void fetchSamplerStats()
  void fetchErrorAggregates()
  if (!isTerminal.value) {
    samplerTimer = window.setInterval(fetchSamplerStats, SAMPLER_POLL_MS)
    errorTimer = window.setInterval(fetchErrorAggregates, ERROR_POLL_MS)
  }
}

function stopTimers() {
  if (samplerTimer != null) {
    clearInterval(samplerTimer)
    samplerTimer = null
  }
  if (errorTimer != null) {
    clearInterval(errorTimer)
    errorTimer = null
  }
}

onMounted(startTimers)
onUnmounted(stopTimers)

// run 切换 / 终态切换都重启轮询
watch(
  [activeRunId, isTerminal],
  ([id, terminal]) => {
    samplerStats.value = []
    errorAggregates.value = []
    if (!id) {
      stopTimers()
      return
    }
    void fetchSamplerStats()
    void fetchErrorAggregates()
    stopTimers()
    if (!terminal) {
      samplerTimer = window.setInterval(fetchSamplerStats, SAMPLER_POLL_MS)
      errorTimer = window.setInterval(fetchErrorAggregates, ERROR_POLL_MS)
    }
  },
)

const overall = computed(() => props.metrics?.overall ?? null)
const byTg = computed(() => props.metrics?.by_tg ?? {})
const byHost = computed(() => props.metrics?.by_host ?? {})
const totals = computed(() => props.metrics?.totals ?? null)

// v1.2 多机切线：>1 host 时允许切到"按主机"看分散度。<=1 不显示按钮，纯按接口。
const splitMode = ref<'tg' | 'host'>('tg')
const hostKeys = computed(() => Object.keys(byHost.value))
const showSplitToggle = computed(() => hostKeys.value.length > 1)
const trendSplit = computed(() =>
  splitMode.value === 'host' && showSplitToggle.value ? byHost.value : byTg.value,
)

const hasAnyData = computed(() => {
  const o = overall.value
  if (!o) return false
  return (
    o.rps.length +
      o.p95_ms.length +
      o.error_count.length +
      o.active_users.length >
    0
  )
})

// 副区块（小图 / 错误表）：标准玻璃感
const sectionStyle = computed(() => ({
  background: props.isDark ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.6)',
  border: props.isDark
    ? '1px solid rgba(255,255,255,0.06)'
    : '1px solid rgba(0,0,0,0.06)',
}))

// 主区块（RPS / RT / Net 三大曲线）：用更亮背景 + 更大内边距表达主次（不加边框/阴影）
// Tufte 第一原则：用空间和字号表达主次，不用线条（避免 chartjunk）
const heroStyle = computed(() => ({
  background: props.isDark ? 'rgba(255,255,255,0.03)' : 'rgba(255,255,255,0.78)',
}))
</script>

<template>
  <div class="h-full overflow-y-auto p-3 space-y-3">
    <!-- 1. 双行 KPI（sticky）：上行"现在"雷达 / 下行"累计"沉淀 -->
    <div
      class="sticky top-[-12px] z-10 -mx-3 px-3 -mt-3 pt-3 pb-2 backdrop-blur"
      :style="{
        background: isDark ? 'rgba(10,10,12,0.85)' : 'rgba(245,245,247,0.85)',
      }"
    >
      <KpiBar :totals="totals" :series="overall" :is-dark="isDark" />
    </div>

    <!-- 2. 健康度小图：错误率 gauge / 错误数 / 并发 / 人均吞吐 -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 h-[200px]">
      <div class="rounded-xl p-3" :style="sectionStyle">
        <ErrorRateGauge :totals="totals" :series="overall" :is-dark="isDark" />
      </div>
      <div class="rounded-xl p-3" :style="sectionStyle">
        <ErrorCountChart
          :data="overall?.error_count || []"
          :is-dark="isDark"
        />
      </div>
      <div class="rounded-xl p-3" :style="sectionStyle">
        <ConcurrencyChart
          :data="overall?.active_users || []"
          :is-dark="isDark"
        />
      </div>
      <div class="rounded-xl p-3" :style="sectionStyle">
        <ThroughputPerVuChart
          :rps="overall?.rps || []"
          :vu="overall?.active_users || []"
          :is-dark="isDark"
        />
      </div>
    </div>

    <!-- 3-5 三大趋势曲线（small multiples 紧贴布局，hover 联动）
         上两张 compact 隐藏 x 轴标签 + 紧贴最底下 NetworkChart 的 x 轴；
         共用一个 hero 容器，垂直对比效率提升。 -->
    <div class="rounded-xl p-4" :style="heroStyle">
      <div class="flex items-center justify-between mb-2 px-1">
        <div
          class="text-[11.5px]"
          :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }"
        >
          趋势曲线（hover 联动 · 共用时间轴）
        </div>
        <!-- 多 host 切线 toggle：仅在 v1.2 多机场景显示 -->
        <div
          v-if="showSplitToggle"
          class="flex text-[11px] rounded-md overflow-hidden"
          :style="{ border: `1px solid ${isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)'}` }"
        >
          <button
            class="px-2 py-0.5 cursor-pointer"
            :style="{
              background: splitMode === 'tg'
                ? (isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.06)')
                : 'transparent',
              color: isDark ? 'rgba(255,255,255,0.75)' : 'rgba(0,0,0,0.7)',
            }"
            @click="splitMode = 'tg'"
          >按接口</button>
          <button
            class="px-2 py-0.5 cursor-pointer"
            :style="{
              background: splitMode === 'host'
                ? (isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.06)')
                : 'transparent',
              color: isDark ? 'rgba(255,255,255,0.75)' : 'rgba(0,0,0,0.7)',
            }"
            @click="splitMode = 'host'"
          >按主机 ({{ hostKeys.length }})</button>
        </div>
      </div>
      <div class="space-y-1">
        <div class="h-[200px]">
          <RpsChart :overall="overall" :by-tg="trendSplit" :is-dark="isDark" compact />
        </div>
        <div class="h-[260px]">
          <LatencyChart :overall="overall" :by-tg="trendSplit" :run-id="activeRunId" :is-dark="isDark" compact />
        </div>
        <div class="h-[220px]">
          <NetworkChart :overall="overall" :by-tg="trendSplit" :is-dark="isDark" />
        </div>
      </div>
    </div>

    <!-- 5.5 并发-吞吐关系散点：看线性增长 / 平台期 / 性能拐点 -->
    <div class="rounded-xl p-3 h-[220px]" :style="sectionStyle">
      <ConcurrencyRpsChart
        :rps="overall?.rps || []"
        :vu="overall?.active_users || []"
        :is-dark="isDark"
      />
    </div>

    <!-- 6. 错误两表 -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-3 h-[280px]">
      <div class="rounded-xl p-3 min-h-0" :style="sectionStyle">
        <ErrorTransactionTable :stats="samplerStats" :is-dark="isDark" />
      </div>
      <div class="rounded-xl p-3 min-h-0" :style="sectionStyle">
        <ErrorMessageTable :rows="errorAggregates" :is-dark="isDark" />
      </div>
    </div>

    <!-- 占位提示（首次 mount + 未拉到任何数据） -->
    <div
      v-if="!hasAnyData"
      class="text-center text-[12px] py-3"
      :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.4)' }"
    >
      暂无指标数据（运行未开始 / 未接入 InfluxDB）
    </div>
  </div>
</template>
