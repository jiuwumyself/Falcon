<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type {
  ErrorAggregateRow, RunMetrics, RunMetricsSeries, Task, TaskRun,
} from '@/types/task'
import { runsApi } from '@/lib/api'
import { hasOnlyArrivals } from '@/lib/planSummary'
import { plannedCurveAlignedToTimestamps, plannedCurve } from '@/lib/plannedCurve'
import KpiBar from './KpiBar.vue'
import ErrorCountChart from './ErrorCountChart.vue'
import ConcurrencyChart from './ConcurrencyChart.vue'
import ThroughputPerVuChart from './ThroughputPerVuChart.vue'
import ConcurrencyRpsChart from './ConcurrencyRpsChart.vue'
import RpsChart from './RpsChart.vue'
import LatencyChart from './LatencyChart.vue'
import NetworkChart from './NetworkChart.vue'
import ErrorByEndpointTable from './ErrorByEndpointTable.vue'

const props = defineProps<{
  task: Task
  run: TaskRun | null
  metrics: RunMetrics | null
  isDark: boolean
}>()

const ERROR_POLL_MS = 10000
const ERROR_LIMIT = 100   // aggregate 模式下 limit 控制聚合后行数（不是样本数），50-100 足够

const TERMINAL_STATUSES: TaskRun['status'][] = [
  'pre_check_failed', 'success', 'failed', 'timeout', 'cancelled',
]

const errorAggregates = ref<ErrorAggregateRow[]>([])

let errorTimer: number | null = null

const activeRunId = computed(() => props.run?.run_id || null)
const isTerminal = computed(
  () => !!props.run && TERMINAL_STATUSES.includes(props.run.status),
)

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
  void fetchErrorAggregates()
  if (!isTerminal.value) {
    errorTimer = window.setInterval(fetchErrorAggregates, ERROR_POLL_MS)
  }
}

function stopTimers() {
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
    errorAggregates.value = []
    if (!id) {
      stopTimers()
      return
    }
    void fetchErrorAggregates()
    stopTimers()
    if (!terminal) {
      errorTimer = window.setInterval(fetchErrorAggregates, ERROR_POLL_MS)
    }
  },
)

const overall = computed(() => props.metrics?.overall ?? null)
const byTg = computed(() => props.metrics?.by_tg ?? {})
const bySampler = computed(() => props.metrics?.by_sampler ?? {})
const samplerToTg = computed(() => props.metrics?.sampler_thread_group ?? {})
const byHost = computed(() => props.metrics?.by_host ?? {})
const totals = computed(() => props.metrics?.totals ?? null)
const totalsByTg = computed(() => props.metrics?.totals_by_tg ?? {})

// v1.2 多机切线：>1 host 时允许切到"按主机"看分散度。<=1 不显示按钮，纯按接口。
const splitMode = ref<'tg' | 'host'>('tg')
const hostKeys = computed(() => Object.keys(byHost.value))
const showSplitToggle = computed(() => hostKeys.value.length > 1)

// ── KpiBar TG 切换：null = 全部（用 overall/totals）；非空 = 单 TG（用 by_tg[key] / totals_by_tg[key]）
// 趋势区所有图都吃 effective* 数据；下方"按接口分错误类型"等表保持全量不受影响。
const tgKeys = computed(() => Object.keys(byTg.value))
const selectedTg = ref<string | null>(null)
// hasUserPicked：区分"首次自动初始化"vs"用户手动切过"。用户切过之后即便 metrics 重拉
// （含切换 run）也保留选择，除非选中的 TG 在新 metrics 里消失。
const hasUserPicked = ref(false)
function setSelectedTg(v: string | null) {
  selectedTg.value = v
  hasUserPicked.value = true
}

// 默认值策略：单 TG → 直接选该 TG（"全部"跟它一样无意义）；多 TG → null（"全部"）。
// 选中的 TG 若在新 metrics 里消失（换 run），自动回退到 null 并允许重新自动初始化。
watch(tgKeys, (keys) => {
  if (selectedTg.value && !keys.includes(selectedTg.value)) {
    selectedTg.value = null
    hasUserPicked.value = false   // run 换了/TG 没了 → 重新走自动默认
  }
  if (!hasUserPicked.value) {
    selectedTg.value = keys.length === 1 ? keys[0] : null
  }
}, { immediate: true })

// per-TG active_users 后端拿不到（JMeter maxAT 在多 listener 时都是全局值），
// 用 metrics.tg_planned_users 里的"计划线程数"渲染一条水平线兜底。
// 注意：这是计划值不是实测；ramp-up 阶段会"假满"，配上 isStatic 提示用户。
const effectiveOverall = computed(() => {
  const tg = selectedTg.value
  if (tg && byTg.value[tg]) {
    const series = byTg.value[tg]
    if (series.active_users.length === 0) {
      // per-TG 实测并发 JMeter 拿不到（maxAT 全局）→ 用配置 kind+params 算计划曲线，
      // 含 ramp-up 渐增 / hold 平台 / shutdown 下降，至少能看到启动波动。
      const meta = props.metrics?.tg_planned_meta?.[tg]
      const startMs = props.run?.started_at ? new Date(props.run.started_at).getTime() : 0
      if (meta && startMs > 0) {
        // 优先按 rps 时间戳对齐采样：ThroughputPerVuChart 按 vu 时间戳查 rps map，
        // 必须 1:1 才能 derive 出非零人均吞吐（rps[i] / planned[i]）。
        if (series.rps.length > 0) {
          const timestamps = series.rps.map(([t]) => t)
          return {
            ...series,
            active_users: plannedCurveAlignedToTimestamps(
              meta.kind, meta.params, startMs, timestamps,
            ),
          }
        }
        // rps 没数据 → 按 1s 密度采样到 finished_at / now
        const endMs = props.run?.finished_at
          ? new Date(props.run.finished_at).getTime()
          : Date.now()
        return {
          ...series,
          active_users: plannedCurve(meta.kind, meta.params, startMs, endMs, 1000),
        }
      }
      // meta 缺失（旧 run / 后端未升级）→ 退到 planned_users 静态线兜底
      const planned = props.metrics?.tg_planned_users?.[tg] ?? 0
      if (planned > 0 && series.rps.length > 0) {
        return {
          ...series,
          active_users: series.rps.map(
            ([t]) => [t, planned] as [number, number],
          ),
        }
      }
    }
    return series
  }
  return overall.value
})
// Arrivals（吞吐量）压测模式：VU 由 JMeter 自适应 → "并发-吞吐"/"RPS 抖动"散点图无意义
// 隐藏整张卡。混合 TG（部分 Arrivals）→ hasOnlyArrivals 返 false → 仍渲染
const hideConcurrencyRpsCard = computed(() =>
  hasOnlyArrivals(props.task.thread_groups_config || []),
)
const effectiveTotals = computed(() => {
  if (selectedTg.value) {
    // 选中具体 TG：必须用 by_tg 切片，缺失（旧 run / 后端未升级）就给 0 totals，
    // 不能回退到合计——否则 KpiBar chips 跟图严重不一致（图是单 TG，chips 是合计）
    return totalsByTg.value[selectedTg.value] ?? {
      total_count: 0,
      total_errors: 0,
      total_bytes_recv: 0,
      total_bytes_sent: 0,
    }
  }
  return totals.value
})
// 三大曲线切线策略（接口级多线，不是 TG 级）：
//   1. 多机模式（splitMode=host）：用 by_host，按 pod 切线
//   2. 选中具体 TG：用 by_sampler 但只保留 sampler_thread_group=<TG> 的那部分
//      → 看到该 TG 内"哪个接口慢/哪个接口出错"的接口级细节
//   3. 默认（全部 TG）：用 by_sampler 全部
//   4. by_sampler 为空（旧 run / 后端未升级）→ fallback 到 by_tg（TG 级粗粒度）
const effectiveTrendSplit = computed<Record<string, RunMetricsSeries>>(() => {
  if (splitMode.value === 'host' && showSplitToggle.value) {
    return byHost.value
  }
  const samplers = bySampler.value
  if (selectedTg.value) {
    if (Object.keys(samplers).length > 0) {
      const out: Record<string, RunMetricsSeries> = {}
      const tg = selectedTg.value
      const mapping = samplerToTg.value
      for (const [label, series] of Object.entries(samplers)) {
        // mapping[label] 是 TG 名列表（同名 sample 跨 TG 时）；用 includes 而非 ===
        if (mapping[label]?.includes(tg)) out[label] = series
      }
      // 该 TG 在 by_sampler 里没有任何 sampler 时退化到 by_tg 单条线（保底）
      if (Object.keys(out).length > 0) return out
    }
    // 旧 run 或映射缺失：fallback 到 TG 级单线
    if (byTg.value[selectedTg.value]) {
      return { [selectedTg.value]: byTg.value[selectedTg.value] }
    }
    return {}
  }
  // 默认：全部 sampler 多线（保留之前接口级粒度）；by_sampler 空就用 by_tg
  return Object.keys(samplers).length > 0 ? samplers : byTg.value
})

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

// 跨图统一 X 轴时间窗：[run.started_at, run.finished_at | now]。
// 让所有小图共用同一刻度，否则 echarts 按各自 series 自适应，截止时间会错。
const xRange = computed<[number, number] | null>(() => {
  const r = props.run
  if (!r?.started_at) return null
  const start = new Date(r.started_at).getTime()
  const end = r.finished_at ? new Date(r.finished_at).getTime() : Date.now()
  if (end <= start) return null
  return [start, end]
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
    <!-- 1. 单行 KPI（sticky）：场景 + 累计 chips + 整体 RPS / P95 / 近 60s 错误率 -->
    <div
      class="sticky top-[-12px] z-10 -mx-3 px-3 -mt-3 pt-3 pb-2 backdrop-blur"
      :style="{
        background: isDark ? 'rgba(10,10,12,0.85)' : 'rgba(245,245,247,0.85)',
      }"
    >
      <KpiBar
        :task="task"
        :run="run"
        :totals="effectiveTotals"
        :series="effectiveOverall"
        :tg-keys="tgKeys"
        :selected-tg="selectedTg"
        :is-dark="isDark"
        @update:selected-tg="setSelectedTg"
      />
    </div>

    <!-- 2. 健康度小图：错误数 / 并发 / 人均吞吐（错误率已搬到 KpiBar fail chip）-->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-3 h-[200px]">
      <div class="rounded-xl p-3" :style="sectionStyle">
        <ErrorCountChart
          :data="effectiveOverall?.error_count || []"
          :rps-data="effectiveOverall?.rps || []"
          :totals="effectiveTotals"
          :run="run"
          :x-range="xRange"
          :is-dark="isDark"
        />
      </div>
      <div class="rounded-xl p-3" :style="sectionStyle">
        <ConcurrencyChart
          :data="effectiveOverall?.active_users || []"
          :x-range="xRange"
          :is-dark="isDark"
        />
      </div>
      <div class="rounded-xl p-3" :style="sectionStyle">
        <ThroughputPerVuChart
          :rps="effectiveOverall?.rps || []"
          :vu="effectiveOverall?.active_users || []"
          :x-range="xRange"
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
          <RpsChart :overall="effectiveOverall" :by-tg="effectiveTrendSplit" :is-dark="isDark" compact />
        </div>
        <div class="h-[260px]">
          <LatencyChart :overall="effectiveOverall" :by-tg="effectiveTrendSplit" :run-id="activeRunId" :is-dark="isDark" compact />
        </div>
        <div class="h-[220px]">
          <NetworkChart :overall="effectiveOverall" :by-tg="effectiveTrendSplit" :is-dark="isDark" />
        </div>
      </div>
    </div>

    <!-- 5.5 并发-吞吐关系散点：看线性增长 / 平台期 / 性能拐点
         Arrivals 场景（吞吐量）下 VU 由 JMeter 自适应，"并发-吞吐"无意义 → 隐藏 -->
    <div v-if="!hideConcurrencyRpsCard" class="rounded-xl p-3 h-[220px]" :style="sectionStyle">
      <ConcurrencyRpsChart
        :rps="effectiveOverall?.rps || []"
        :vu="effectiveOverall?.active_users || []"
        :is-dark="isDark"
      />
    </div>

    <!-- 6. 错误统计表（按 接口 + code + message 三键聚合，count desc 排序） -->
    <div class="rounded-xl p-3 min-h-0 h-[320px]" :style="sectionStyle">
      <ErrorByEndpointTable :rows="errorAggregates" :is-dark="isDark" />
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
