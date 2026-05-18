<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type {
  RunMetrics, RunMetricsSeries, Task, TaskRun,
} from '@/types/task'
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

const props = defineProps<{
  task: Task
  run: TaskRun | null
  metrics: RunMetrics | null
  isDark: boolean
}>()

// v1.3 起 Trends 不再承载错误数据：聚合表 + 单条样本下钻都搬进 Errors tab，
// Trends 专注 6 张时序图（看大盘 / 趋势 / 形状）。

const activeRunId = computed(() => props.run?.run_id || null)

const overall = computed(() => props.metrics?.overall ?? null)
const byTg = computed(() => props.metrics?.by_tg ?? {})
const bySampler = computed(() => props.metrics?.by_sampler ?? {})
const bySamplerByTg = computed(() => props.metrics?.by_sampler_by_tg ?? {})
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
//
// 全部模式（selectedTg=null）也走 plannedCurve 加总 —— 后端 overall.active_users
// 来自 JMeter 全局 maxAT，多 listener 重复写时 max 出来的值跟各 TG 实际计划并发的
// 加和对不上（实测：maxAT=10，学生端 5 + 教师端 2 = 7）。前端按各 TG plannedCurve
// 按 ts 相加保证「全部并发数 = 各 TG 并发数加和」语义一致。
const effectiveOverall = computed(() => {
  const tg = selectedTg.value
  const startMs = props.run?.started_at ? new Date(props.run.started_at).getTime() : 0
  const meta = props.metrics?.tg_planned_meta

  // —— 1. 选中具体 TG：用 byTg 切片 + per-TG plannedCurve 兜底 active_users ——
  if (tg && byTg.value[tg]) {
    const series = byTg.value[tg]
    if (series.active_users.length === 0) {
      // per-TG 实测并发 JMeter 拿不到（maxAT 全局）→ 用配置 kind+params 算计划曲线
      const m = meta?.[tg]
      if (m && startMs > 0) {
        if (series.rps.length > 0) {
          const timestamps = series.rps.map(([t]) => t)
          return {
            ...series,
            active_users: plannedCurveAlignedToTimestamps(
              m.kind, m.params, startMs, timestamps,
            ),
          }
        }
        const endMs = props.run?.finished_at
          ? new Date(props.run.finished_at).getTime()
          : Date.now()
        return {
          ...series,
          active_users: plannedCurve(m.kind, m.params, startMs, endMs, 1000),
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

  // —— 2. 全部模式：active_users 用各 TG plannedCurve 按 ts 相加（替代后端 maxAT）
  const base = overall.value
  if (!base) return null
  const metaEntries = Object.entries(meta || {})
  if (metaEntries.length > 0 && startMs > 0 && base.rps.length > 0) {
    const timestamps = base.rps.map(([t]) => t)
    // 每个 TG 算一份对齐 plannedCurve（时间戳跟 rps 一致 → 长度一致，逐点 sum）
    const sums = new Array(timestamps.length).fill(0)
    for (const [, m] of metaEntries) {
      const curve = plannedCurveAlignedToTimestamps(m.kind, m.params, startMs, timestamps)
      for (let i = 0; i < curve.length && i < sums.length; i++) {
        sums[i] += curve[i][1]
      }
    }
    return {
      ...base,
      active_users: timestamps.map((t, i) => [t, sums[i]] as [number, number]),
    }
  }
  return base
})
// 末位「场景上下文图」始终显示——内部按场景分发：
//   baseline/load/soak → ConcurrencyRpsChart
//   stress → ErrorBreakdownStackedChart
//   spike → VuRpsDualAxisChart
//   throughput → TargetRpsVsActualChart（专门为 Arrivals 场景设计，不再硬隐）
// 旧 hasOnlyArrivals 隐藏逻辑已废弃：throughput 场景下展示目标 vs 实际对比，比硬隐有信息量
const isTerminal = computed(() => {
  const s = props.run?.status
  return s ? ['pre_check_failed', 'success', 'failed', 'timeout', 'cancelled'].includes(s) : false
})
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
  const r = props.run
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
  const meta = props.metrics?.tg_planned_meta
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
            :is-dark="isDark"
            @toggle-sampler="toggleSampler"
          />
        </div>
      </div>
    </div>

    <!-- 5.5 场景上下文图：末位卡按 6 场景分发到不同组件
         baseline/load/soak → ConcurrencyRpsChart（散点 / RPS 抖动）
         stress → ErrorBreakdownStackedChart（5 桶堆叠）
         spike → VuRpsDualAxisChart（双轴对比）
         throughput → TargetRpsVsActualChart（目标 vs 实际）
         多 TG 时切 selectedTg 跟随切图 -->
    <div v-if="showScenarioCard" class="rounded-xl p-3 h-[220px]" :style="sectionStyle">
      <ScenarioContextChart
        :task="task"
        :selected-tg="selectedTg"
        :rps="effectiveOverall?.rps || []"
        :vu="effectiveOverall?.active_users || []"
        :by-tg="byTg"
        :tg-planned-meta="metrics?.tg_planned_meta || {}"
        :run-id="activeRunId"
        :is-terminal="isTerminal"
        :x-range="xRange"
        :is-dark="isDark"
      />
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
