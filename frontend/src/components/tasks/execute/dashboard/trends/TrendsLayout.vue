<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import type {
  ConcurrencyResponse, RunMetrics, RunMetricsSeries, SamplerStat, SeriesPoint, Task, TaskRun,
} from '@/types/task'
import { runsApi } from '@/lib/api'
import { plannedCurveAlignedToTimestamps, plannedCurve } from '@/lib/plannedCurve'
import KpiBar from './KpiBar.vue'
import ErrorCountChart from './ErrorCountChart.vue'
import ConcurrencyChart from './ConcurrencyChart.vue'
import ThroughputPerVuChart from './ThroughputPerVuChart.vue'
import ScenarioContextChart from './ScenarioContextChart.vue'
import RpsChart from './RpsChart.vue'
import LatencyChart from './LatencyChart.vue'
import NetworkChart from './NetworkChart.vue'
import { inferScenarioFromKind } from './scenarioCtx'
import { buildMockBundle } from './trendsMockData'

const props = defineProps<{
  task: Task
  run: TaskRun | null
  runs: TaskRun[]            // 末位 baseline 图②找本任务星标的历史基准 run 用
  metrics: RunMetrics | null
  isDark: boolean
}>()

// v1.3 起 Trends 不再承载错误数据：聚合表 + 单条样本下钻都搬进 Errors tab，
// Trends 专注 6 张时序图（看大盘 / 趋势 / 形状）。

// 🎭 mock 预览：开关打开后整页换成 6-TG 合成 run（每 TG 一个场景），看末位场景图效果。
// 真实数据源接入前用，纯前端编造数据；关掉即恢复真实 metrics。
const mockMode = ref(false)
const mockBundle = buildMockBundle()
const eMetrics = computed(() => (mockMode.value ? mockBundle.metrics : props.metrics))
const eRun = computed(() => (mockMode.value ? mockBundle.run : props.run))

const activeRunId = computed(() => eRun.value?.run_id || null)

const overall = computed(() => eMetrics.value?.overall ?? null)
const byTg = computed(() => eMetrics.value?.by_tg ?? {})
const bySampler = computed(() => eMetrics.value?.by_sampler ?? {})
const bySamplerByTg = computed(() => eMetrics.value?.by_sampler_by_tg ?? {})
const samplerToTg = computed(() => eMetrics.value?.sampler_thread_group ?? {})
const byHost = computed(() => eMetrics.value?.by_host ?? {})
const totals = computed(() => eMetrics.value?.totals ?? null)
const totalsByTg = computed(() => eMetrics.value?.totals_by_tg ?? {})

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

// ── 并发数 = 实测(JTL) + 计划曲线 ──────────────────────────────────────
// 后端 InfluxDB 的 maxAT 是全局值切不开 per-TG，所以实测并发改走独立的 JTL 端点
// （allThreads 总 / grpThreads per-TG 每秒峰值）。计划曲线仍用 plannedCurve 算。
// ConcurrencyChart 把实测画实线、计划画虚线叠加；ThroughputPerVuChart 等用"实测优先"
// 的最佳估计(effectiveOverall.active_users)。
const realConcurrency = ref<ConcurrencyResponse | null>(null)

// 计划并发曲线：单 TG → dense plannedCurve；全部 → 各 TG 按 rps 时间戳相加。
// meta 缺失(旧 run)→ planned_users 静态线兜底。
//
// ArrivalsThreadGroup(吞吐量)模式不画计划线:它是到达率驱动,线程数由 JMeter 动态
// 调,**没有"计划并发"**这回事。plannedCurve 对 Arrivals 画的是 target_rps(到达率,
// arrivals/sec),跟实测的线程数(threads)单位不同,叠在并发(VU)轴上会误导。
// 吞吐量的"目标 vs 实际"对比看末位的"目标 RPS vs 实际 RPS"图(同单位 RPS)。
function plannedActiveUsersFor(tg: string | null): SeriesPoint[] {
  const startMs = eRun.value?.started_at ? new Date(eRun.value.started_at).getTime() : 0
  if (startMs <= 0) return []
  const meta = eMetrics.value?.tg_planned_meta
  const endMs = eRun.value?.finished_at
    ? new Date(eRun.value.finished_at).getTime()
    : Date.now()
  if (tg) {
    const m = meta?.[tg]
    if (m) {
      if (m.kind === 'ArrivalsThreadGroup') return []   // 到达率驱动,无计划并发
      return plannedCurve(m.kind, m.params, startMs, endMs, 1000)
    }
    const planned = eMetrics.value?.tg_planned_users?.[tg] ?? 0
    const series = byTg.value[tg]
    if (planned > 0 && series?.rps?.length) {
      return series.rps.map(([t]) => [t, planned] as SeriesPoint)
    }
    return []
  }
  // 全部：各 TG plannedCurve 按 rps 时间戳逐点相加（保证总并发 = 各 TG 加和）。
  // Arrivals TG 跳过(无计划并发);全是 Arrivals 时 sums 恒 0 → 返回空不画线。
  const base = overall.value
  const metaEntries = Object.entries(meta || {})
    .filter(([, m]) => m.kind !== 'ArrivalsThreadGroup')
  if (base && metaEntries.length > 0 && base.rps.length > 0) {
    const timestamps = base.rps.map(([t]) => t)
    const sums = new Array(timestamps.length).fill(0)
    for (const [, m] of metaEntries) {
      const curve = plannedCurveAlignedToTimestamps(m.kind, m.params, startMs, timestamps)
      for (let i = 0; i < curve.length && i < sums.length; i++) sums[i] += curve[i][1]
    }
    return timestamps.map((t, i) => [t, sums[i]] as SeriesPoint)
  }
  return []
}

// 实测并发(JTL 端点)：单 TG → by_tg[tg]；全部 → overall。空数组 = 还没拉到/无数据。
const realActiveUsers = computed<SeriesPoint[]>(() => {
  const rc = realConcurrency.value
  if (!rc) return []
  const tg = selectedTg.value
  return (tg ? rc.by_tg[tg] : rc.overall) ?? []
})
const plannedActiveUsers = computed<SeriesPoint[]>(() => plannedActiveUsersFor(selectedTg.value))

const effectiveOverall = computed<RunMetricsSeries | null>(() => {
  const tg = selectedTg.value
  const base = (tg && byTg.value[tg]) ? byTg.value[tg] : overall.value
  if (!base) return null
  // active_users 优先实测(JTL)，没拉到则用计划曲线 —— 给 ThroughputPerVuChart /
  // ScenarioContextChart 一个"最佳估计"。ConcurrencyChart 另走 real+planned 双线。
  const real = realActiveUsers.value
  return { ...base, active_users: real.length ? real : plannedActiveUsers.value }
})
// 末位「场景上下文图」始终显示——内部按场景分发：
//   baseline/load/stress → ConcurrencyRpsChart（load 看拐点，stress 看容量悬崖）
//   soak → SoakLatencyTrendChart（p95 RT 随时间 + 回归线，抓延迟爬升泄漏）
//   spike → VuRpsDualAxisChart
//   throughput → TargetRpsVsActualChart（专门为 Arrivals 场景设计，不再硬隐）
// 旧 hasOnlyArrivals 隐藏逻辑已废弃：throughput 场景下展示目标 vs 实际对比，比硬隐有信息量
const isTerminal = computed(() => {
  const s = eRun.value?.status
  return s ? ['pre_check_failed', 'success', 'failed', 'timeout', 'cancelled'].includes(s) : false
})

// 拉真实并发(JTL 端点)：运行中 5s 轮询(JTL 周期增长)、终态 one-shot。
let concurrencyTimer: ReturnType<typeof setInterval> | null = null
async function fetchConcurrency() {
  const id = activeRunId.value
  if (!id) { realConcurrency.value = null; return }
  try {
    realConcurrency.value = await runsApi.concurrency(id)
  } catch {
    // 失败保留旧数据，下一轮再试
  }
}
function stopConcurrencyPoll() {
  if (concurrencyTimer != null) { clearInterval(concurrencyTimer); concurrencyTimer = null }
}
watch(
  () => [activeRunId.value, isTerminal.value, mockMode.value] as const,
  ([id, terminal, mock]) => {
    stopConcurrencyPoll()
    if (mock) { realConcurrency.value = mockBundle.concurrency; return }  // mock：直接喂，不轮询
    if (!id) { realConcurrency.value = null; return }
    void fetchConcurrency()
    if (!terminal) concurrencyTimer = window.setInterval(fetchConcurrency, 5000)
  },
  { immediate: true },
)
onUnmounted(stopConcurrencyPoll)

// ── 末位图② 取数：throughput 气泡(samplerStats) + baseline 版本对比 ─────────
// 终态 one-shot 拉本 run 的接口统计；本任务有星标基准 run 时再拉它的，组成对比。
const samplerStats = ref<SamplerStat[]>([])
const baselineStats = ref<SamplerStat[]>([])
const baselineRunId = computed(() =>
  props.runs.find((r) => r.is_baseline && r.run_id !== activeRunId.value)?.run_id ?? null,
)

// SamplerStat 'all' 行 → {avg, p90, p99}（BaselineVersionBar 吃这个形状）
function verOf(stats: SamplerStat[]): { avg: number; p90: number; p99: number } | null {
  const all = stats.find((s) => s.label === 'all') ?? stats[0]
  if (!all) return null
  return { avg: all.avg_ms, p90: all.p90_ms, p99: all.p99_ms }
}
// 本次自己的数据有就传（终态后），baseline 仅当「存在另一个星标基准 run」且「自己不是基准」才给。
// 自己是基准 → 永远只显示自己；没设基准 → 也只显示自己（带提示，星标后才对比）。
const baselineCompare = computed(() => {
  const cur = verOf(samplerStats.value)
  if (!cur) return null   // 本次还没接口统计（运行中/无数据）→ ScenarioPair 占位
  const selfIsBaseline = !!eRun.value?.is_baseline
  const base = selfIsBaseline ? null : verOf(baselineStats.value)
  return { current: cur, baseline: base, selfIsBaseline }
})

watch(
  () => [activeRunId.value, isTerminal.value, baselineRunId.value, mockMode.value] as const,
  async ([id, terminal, baseId, mock]) => {
    if (mock || !id || !terminal) {
      samplerStats.value = []; baselineStats.value = []
      return
    }
    try { samplerStats.value = await runsApi.samplerStats(id) } catch { samplerStats.value = [] }
    if (baseId) {
      try { baselineStats.value = await runsApi.samplerStats(baseId) } catch { baselineStats.value = [] }
    } else {
      baselineStats.value = []
    }
  },
  { immediate: true },
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
//   2. 选中具体 TG：优先用 by_sampler_by_tg[label][tg] 双键切片
//      → 看到该 TG 内"哪个接口慢/哪个接口出错"的接口级细节，跨 TG 同名 sampler
//        不再混在一起（2026-05-17 修：原走 by_sampler 单维聚合，同名 sampler 跨
//        TG 时数据被叠加 → 切 TG 后仍显示全部）
//   3. 默认（全部 TG）：用 by_sampler（单维 transaction GROUP BY，每接口一条线）
//   4. 旧 run / 后端未升级：by_sampler_by_tg 空 → fallback 到 by_sampler 过滤映射
//      → 再退到 by_tg 单线
const effectiveTrendSplit = computed<Record<string, RunMetricsSeries>>(() => {
  if (splitMode.value === 'host' && showSplitToggle.value) {
    return byHost.value
  }
  if (selectedTg.value) {
    const tg = selectedTg.value
    // 主路径：by_sampler_by_tg 双键直接拿
    const byLabel = bySamplerByTg.value
    if (Object.keys(byLabel).length > 0) {
      const out: Record<string, RunMetricsSeries> = {}
      for (const [label, perTg] of Object.entries(byLabel)) {
        if (perTg[tg]) out[label] = perTg[tg]
      }
      if (Object.keys(out).length > 0) return out
    }
    // 老 run 兼容：by_sampler_by_tg 空 → 走 by_sampler + sampler_thread_group
    // 注意：跨 TG 同名 sampler 时数据是混合的（这是旧 bug 行为），仅为兼容
    const samplers = bySampler.value
    if (Object.keys(samplers).length > 0) {
      const out: Record<string, RunMetricsSeries> = {}
      const mapping = samplerToTg.value
      for (const [label, series] of Object.entries(samplers)) {
        if (mapping[label]?.includes(tg)) out[label] = series
      }
      if (Object.keys(out).length > 0) return out
    }
    // 兜底：TG 级单线
    if (byTg.value[tg]) {
      return { [tg]: byTg.value[tg] }
    }
    return {}
  }
  // 默认：全部 sampler 多线；by_sampler 空就用 by_tg
  const samplers = bySampler.value
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
  const r = eRun.value
  if (!r?.started_at) return null
  const start = new Date(r.started_at).getTime()
  const end = r.finished_at ? new Date(r.finished_at).getTime() : Date.now()
  if (end <= start) return null
  return [start, end]
})

// ── 共享 「剔除失败样本」toggle：影响 3 张趋势图。后端按 statut='ok' 切片：
// LatencyChart 用 p50/95/99_ok_ms；NetworkChart 用 bytes_recv_ok/bytes_sent_ok；
// RpsChart 前端用 rps - error_count（每秒精确扣减）。三处都有效。
const excludeKo = ref(false)

// run 有失败样本才让 toggle 真生效；0 错误时 _ok 系列是后端跨 sampler mean-of-means
// 近似（详见 backend/services/influxdb.py:226），跟 'all' 行数学维度不同，无脑切换会
// 让 latency / network 'all' 线数值变化但语义错位（0 fail 还在剔）。
// 主判断用 metrics.totals.total_errors —— 每轮轮询都实时算，运行中就有值；
// run.error_rate 只在 _on_finish 终态才填，运行中是 0，单用它会导致"运行中
// latency/network 剔不掉、终态才能剔"（RPS 走 error_count 实时扣减不受影响）。
const hasErrors = computed(() =>
  (eMetrics.value?.totals?.total_errors ?? 0) > 0
  || (eRun.value?.error_rate ?? 0) > 0,
)

// ── 共享接口 legend：3 张图共用一份 samplerSelected。
// 点击右侧 220 列里的接口名 → 3 张图同步隐藏 / 显示该 series。
const samplerSelected = ref<Record<string, boolean>>({})
const samplerInited = ref(false)

// effectiveTrendSplit 的 key 集合 = 接口 list（splitMode=host 时是 pod 列表）
const samplerNames = computed(() => Object.keys(effectiveTrendSplit.value).sort())

// 默认勾选 = 'all' + 全部接口；新接口出现也默认勾选。
// 用户偏好「先看全」而非「按 RPS top-N 隐藏」；接口太多图糊时用户手动取消即可。
watch(
  samplerNames,
  (names) => {
    if (samplerInited.value) {
      // 新出现的 key 默认勾选（保留用户已切换的选择）
      const next = { ...samplerSelected.value }
      let changed = false
      for (const n of names) {
        if (!(n in next)) { next[n] = true; changed = true }
      }
      if (changed) samplerSelected.value = next
      return
    }
    if (!names.length && !overall.value?.rps.length) return
    const init: Record<string, boolean> = { all: true }
    for (const n of names) init[n] = true
    samplerSelected.value = init
    samplerInited.value = true
  },
  { immediate: true },
)

// 末位场景卡显示条件：
//   · 选了具体 TG → 一律显示（该 TG 场景已确定）
//   · 全部模式 → 仅当所有 TG 场景同质时显示；多场景混合 → 整块隐藏（散点图无意义）
const showScenarioCard = computed(() => {
  if (selectedTg.value) return true
  const meta = eMetrics.value?.tg_planned_meta
  if (!meta) return true   // meta 还没拉到，先显示兜底图，避免页面跳动
  const ids = Object.values(meta).map((m) =>
    m.scenario ?? inferScenarioFromKind(m.kind),
  )
  if (!ids.length) return true
  return new Set(ids).size === 1
})

function toggleSampler(name: string) {
  samplerSelected.value = {
    ...samplerSelected.value,
    [name]: samplerSelected.value[name] === false ? true : !samplerSelected.value[name],
  }
  // undefined → toggle 第一次会 true；上面三元保险：false→true / true→false
}

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
      <div class="flex items-start gap-2">
        <div class="flex-1 min-w-0">
          <KpiBar
            :task="task"
            :run="eRun"
            :totals="effectiveTotals"
            :series="effectiveOverall"
            :tg-keys="tgKeys"
            :selected-tg="selectedTg"
            :is-dark="isDark"
            @update:selected-tg="setSelectedTg"
          />
        </div>
        <!-- 🎭 mock 预览开关（真实数据源接入前临时用，纯前端编造数据）-->
        <button
          type="button"
          class="flex-shrink-0 self-center text-[10.5px] px-2 py-0.5 rounded-full cursor-pointer transition-colors"
          :style="{
            background: mockMode ? 'rgba(236,72,153,0.16)' : (isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)'),
            color: mockMode ? '#ec4899' : (isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)'),
            border: `1px solid ${mockMode ? 'rgba(236,72,153,0.4)' : 'transparent'}`,
          }"
          title="仅前端预览：用编造数据渲染 6 个场景的末位图（真实数据接入前临时用）"
          @click="mockMode = !mockMode"
        >🎭 模拟场景数据{{ mockMode ? ' ●' : '' }}</button>
      </div>
    </div>

    <!-- 2. 健康度小图：错误数 / 并发 / 人均吞吐（错误率已搬到 KpiBar fail chip）-->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-3 h-[200px]">
      <div class="rounded-xl p-3" :style="sectionStyle">
        <ErrorCountChart
          :data="effectiveOverall?.error_count || []"
          :rps-data="effectiveOverall?.rps || []"
          :totals="effectiveTotals"
          :run="eRun"
          :x-range="xRange"
          :is-dark="isDark"
        />
      </div>
      <div class="rounded-xl p-3" :style="sectionStyle">
        <ConcurrencyChart
          :data="realActiveUsers"
          :planned-data="plannedActiveUsers"
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
      <div class="flex items-center justify-between mb-2 px-1 gap-3">
        <!-- 左侧：标题 + 紧跟「剔除失败样本」-->
        <div class="flex items-center gap-3">
          <div
            class="text-[11.5px]"
            :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }"
          >
            趋势曲线（hover 联动 · 共用时间轴）
          </div>
          <label
            class="flex items-center gap-1 text-[11px] cursor-pointer"
            :title="'剔除失败样本（success=false）后看真实业务表现。\n· 延迟：切到 P50/P95/P99 OK 系列\n· RPS：rps - error_count（每秒精确剔除）\n· 网络流量：切到 bytes_recv_ok/bytes_sent_ok（仅 OK 样本）'"
            :style="{ color: isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.6)' }"
          >
            <input type="checkbox" v-model="excludeKo" class="cursor-pointer" />
            剔除失败样本
          </label>
        </div>
        <!-- 右侧：多 host 切线 toggle（v1.2 多机场景才显示）-->
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
      <!-- 3 张图竖叠；每张图自己渲染右侧 Mean/Max 表，点击行 emit('toggleSampler')
           → TrendsLayout 写 samplerSelected → 3 张图同步切换 -->
      <div class="space-y-1">
        <div class="h-[200px]">
          <RpsChart
            :overall="effectiveOverall"
            :by-tg="effectiveTrendSplit"
            :sampler-selected="samplerSelected"
            :exclude-ko="excludeKo"
            :is-dark="isDark"
            compact
            @toggle-sampler="toggleSampler"
          />
        </div>
        <div class="h-[260px]">
          <LatencyChart
            :overall="effectiveOverall"
            :by-tg="effectiveTrendSplit"
            :sampler-selected="samplerSelected"
            :exclude-ko="excludeKo"
            :has-errors="hasErrors"
            :run-id="activeRunId"
            :is-dark="isDark"
            compact
            @toggle-sampler="toggleSampler"
          />
        </div>
        <div class="h-[220px]">
          <NetworkChart
            :overall="effectiveOverall"
            :by-tg="effectiveTrendSplit"
            :sampler-selected="samplerSelected"
            :exclude-ko="excludeKo"
            :has-errors="hasErrors"
            :is-dark="isDark"
            @toggle-sampler="toggleSampler"
          />
        </div>
      </div>
    </div>

    <!-- 5.5 场景上下文图：末位卡按 6 场景分发到不同组件
         baseline/load/stress → ConcurrencyRpsChart（散点 / 拐点 / 容量悬崖）
         soak → SoakLatencyTrendChart（p95 RT 随时间 + 回归线）
         spike → VuRpsDualAxisChart（双轴对比）
         throughput → TargetRpsVsActualChart（目标 vs 实际）
         多 TG 时切 selectedTg 跟随切图 -->
    <div
      v-if="mockMode || showScenarioCard"
      class="rounded-xl p-3"
      :class="mockMode ? '' : 'h-[240px]'"
      :style="sectionStyle"
    >
      <ScenarioContextChart
        :task="task"
        :selected-tg="selectedTg"
        :rps="effectiveOverall?.rps || []"
        :vu="effectiveOverall?.active_users || []"
        :lat="effectiveOverall?.p95_ms || []"
        :vu-is-real="realActiveUsers.length > 0"
        :by-tg="byTg"
        :tg-planned-meta="eMetrics?.tg_planned_meta || {}"
        :sampler-thread-group="samplerToTg"
        :x-range="xRange"
        :is-dark="isDark"
        :run-id="activeRunId"
        :is-terminal="isTerminal"
        :sampler-stats="samplerStats"
        :baseline-compare="baselineCompare"
        :mock-mode="mockMode"
        :mock-scenarios="mockMode ? mockBundle.scenarios : undefined"
        :mock-x-range="mockMode ? mockBundle.xRange : null"
      />
    </div>

    <!-- 占位提示：仅在「已有 run 但拉不到数据」时显示（多半是没接 InfluxDB）。
         新任务（无 run）不显示，靠 0 值 KPI + 空网格表达，避免显得很空。 -->
    <div
      v-if="!hasAnyData && eRun"
      class="text-center text-[12px] py-3"
      :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.4)' }"
    >
      暂无指标数据（运行未开始 / 未接入 InfluxDB）
    </div>
  </div>
</template>
