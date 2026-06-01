<script setup lang="ts">
import { computed } from 'vue'
import type {
  RunMetricsSeries, SamplerStat, ScenarioId, SeriesPoint, Task, TGKind,
} from '@/types/task'
import {
  scenarioById, inferScenarioFromKind, type ScenarioDef,
} from './scenarioCtx'
import ConcurrencyRpsChart from './ConcurrencyRpsChart.vue'
import ScenarioPair from './ScenarioPair.vue'
import type { ScenarioMockSpec } from './trendsMockData'

interface VerStat { avg: number; p90: number; p99: number }

// 末位「场景上下文图」容器：按当前选中 TG 的场景分发渲染。
//
// 分发逻辑：
//   - selectedTg 非空 → 用 tg_planned_meta[selectedTg].scenario 决定图 +
//     用 byTg[selectedTg] 切片 rps/vu（不再用合计值，避免单 TG 切片图
//     拿合计数据失真）
//   - selectedTg = null（全部）→
//       · 所有 TG scenario 同质 → 用该 scenario
//       · 混合场景 → 顶部加提示「多场景混合，建议切具体 TG」+ 退到散点图
//   - meta 缺失（老 run / snapshot 空）→ 兜底走 inferScenarioFromKind +
//     thread_groups_config[0]
//
// 场景 → 图映射：
//   baseline   → ConcurrencyRpsChart (isFlatVu 分支自动触发 RPS 抖动)
//   load       → ConcurrencyRpsChart (非 flat 散点：看拐点)
//   stress     → ConcurrencyRpsChart (压过拐点：看吞吐见顶 + 回落的容量悬崖)
//   soak       → SoakLatencyTrendChart (p95 RT 随时间 + 回归线：抓延迟爬升泄漏)
//   spike      → VuRpsDualAxisChart (双轴时序：VU/RPS 跟随)
//   throughput → TargetRpsVsActualChart (目标 vs 实际)
const props = defineProps<{
  task: Task
  selectedTg: string | null
  // 全部模式 (selectedTg=null) 的合计 rps/vu
  rps: SeriesPoint[]
  vu: SeriesPoint[]
  // soak 场景 RT 趋势用的 p95 延迟时序（合计）
  lat: SeriesPoint[]
  // vu 是否实测(JTL)。true → 不标"计划";父组件按 realActiveUsers 是否非空传
  vuIsReal?: boolean
  // 单 TG 选中时切片来源（key = TG testname）
  byTg: Record<string, RunMetricsSeries>
  // 后端按 testname 给的 {kind, params, scenario}
  tgPlannedMeta: Record<string, { kind: TGKind; params: Record<string, any>; scenario?: ScenarioId | null }>
  // sampler→[TG name 列表] 映射；throughput 场景下要 × samplers_per_TG 把
  // arrivals/sec 换算成可跟 actual rps 对比的 samples/sec
  samplerThreadGroup?: Record<string, string[]>
  xRange?: [number, number] | null
  isDark: boolean
  // 真实模式图②取数（TrendsLayout 拉好传入）：
  runId?: string | null                 // stress 错误堆叠自取
  isTerminal?: boolean
  samplerStats?: SamplerStat[]          // throughput 气泡
  // baseline 版本对比：baseline=null 表示只展示本次自己（没基准 / 自己是基准）
  baselineCompare?: { current: VerStat; baseline: VerStat | null; selfIsBaseline?: boolean } | null
  // mock 预览：开了走 ScenarioPair 分发；selectedTg 命中某场景 label → 单卡(2 图)，
  // 否则全 6 场景画廊（每段 2 图）。
  mockMode?: boolean
  mockScenarios?: ScenarioMockSpec[]
  mockXRange?: [number, number] | null
}>()

interface ResolvedCtx {
  scenario: ScenarioDef
  rps: SeriesPoint[]
  vu: SeriesPoint[]
  lat: SeriesPoint[]
  targetRpsPerSec: number | null
  mixed: boolean    // 多场景混合提示
  vuIsPlanned: boolean   // 单 TG 时 active_users 实测不可拆（InfluxDB maxAT 全局），
                          // 退到 snapshot 计划曲线；UI 标"计划"，避免误读为实测
}

// 单 TG 切片时 active_users 拿不到真切片（见 backend/services/influxdb.py:439）。
// 父组件 TrendsLayout 已经把 effectiveOverall.active_users 替换成该 TG 的 plannedCurve
// （所有 5 种 kind 都支持），透传到 props.vu —— 这里只需要在 slice.active_users 空
// 时退到 props.vu，不再自己重算。

function resolveScenarioId(kind: TGKind, scenario?: ScenarioId | null): ScenarioId {
  return scenario ?? inferScenarioFromKind(kind)
}

// 数 TG 内启用的 sampler 个数：从 sampler_thread_group 倒查（每个 sampler 知道自己
// 属于哪些 TG，反向计数）。throughput 场景 target_rps 是 arrivals/sec（=每秒新 thread
// 迭代数），而 actual RPS 是 samples/sec（每个迭代会跑完该 TG 内全部 sampler），
// 两者差 N 倍（N=该 TG 启用 sampler 数）。target × N 才能跟 actual 同尺度比较。
function countSamplersInTg(
  tgName: string,
  samplerThreadGroup?: Record<string, string[]>,
): number {
  if (!samplerThreadGroup) return 0
  let n = 0
  for (const [, tgs] of Object.entries(samplerThreadGroup)) {
    if (tgs.includes(tgName)) n++
  }
  return n
}

function targetRpsFromParams(
  scenarioId: ScenarioId,
  params: Record<string, any>,
  samplersPerIter: number,
): number | null {
  if (scenarioId !== 'throughput') return null
  const t = Number(params?.target_rps ?? 0)
  if (!t || t <= 0) return null
  const unit = (params?.unit as string) === 'M' ? 60 : 1
  // 没数到 sampler 数（早期没拉到 metrics）就退到原始 target_rps 不放大，
  // 至少不会比 actual 偏大；拉到后值会刷新。
  const mult = samplersPerIter > 0 ? samplersPerIter : 1
  return (t / unit) * mult
}

const ctx = computed<ResolvedCtx | null>(() => {
  // —— 1. selectedTg 非空：lookup 单 TG meta + byTg 切片 ——
  if (props.selectedTg) {
    const meta = props.tgPlannedMeta?.[props.selectedTg]
    if (meta) {
      const id = resolveScenarioId(meta.kind, meta.scenario)
      const slice = props.byTg?.[props.selectedTg]
      const actualVu = slice?.active_users ?? []
      // slice 没切到 vu 就退到 props.vu —— 父组件 TrendsLayout 已经把
      // effectiveOverall.active_users 算成该 TG 的 plannedCurve 了，无需重算
      const useFallbackVu = actualVu.length === 0 && props.vu.length > 0
      return {
        scenario: scenarioById(id),
        rps: slice?.rps ?? props.rps,
        vu: useFallbackVu ? props.vu : actualVu,
        lat: slice?.p95_ms?.length ? slice.p95_ms : props.lat,
        targetRpsPerSec: targetRpsFromParams(id, meta.params, countSamplersInTg(props.selectedTg, props.samplerThreadGroup)),
        mixed: false,
        // props.vu 现在是"实测优先"(real||planned)；real 时不标计划
        vuIsPlanned: useFallbackVu && !props.vuIsReal,
      }
    }
    // meta 缺失：fall through 走 cfgs[0] 兜底
  }

  // —— 2. selectedTg 空（全部）或 meta 缺失 ——
  // 优先用 tg_planned_meta 推断"同质 / 混合"，老 run 无 meta 时退到
  // task.thread_groups_config 的 scenario 字段
  const metaEntries = Object.entries(props.tgPlannedMeta || {})
  if (metaEntries.length > 0) {
    const ids = metaEntries.map(([, m]) =>
      resolveScenarioId(m.kind, m.scenario),
    )
    const unique = Array.from(new Set(ids))
    if (unique.length === 1) {
      const id = unique[0]
      // 同质场景：用第一个 TG 的 params 算 target（throughput 多 TG 时取第一个为代表）
      const [firstTgName, firstMeta] = metaEntries[0]
      return {
        scenario: scenarioById(id),
        rps: props.rps,
        vu: props.vu,
        lat: props.lat,
        targetRpsPerSec: targetRpsFromParams(id, firstMeta.params, countSamplersInTg(firstTgName, props.samplerThreadGroup)),
        mixed: false,
        vuIsPlanned: false,
      }
    }
    // 混合场景：通用散点图兜底 + 顶部提示
    return {
      scenario: scenarioById('load'),  // load 的散点解读最通用
      rps: props.rps,
      vu: props.vu,
      lat: props.lat,
      targetRpsPerSec: null,
      mixed: true,
      vuIsPlanned: false,
    }
  }

  // —— 3. meta 完全空（老 run / 还没拉 metrics）→ task.thread_groups_config 兜底 ——
  const cfgs = props.task.thread_groups_config || []
  if (!cfgs.length) return null
  const cfg = cfgs[0]
  const id = resolveScenarioId(cfg.kind, cfg.scenario)
  return {
    scenario: scenarioById(id),
    rps: props.rps,
    vu: props.vu,
    lat: props.lat,
    targetRpsPerSec: targetRpsFromParams(id, cfg.params || {}, 0),  // 老 run 无 metrics 时不放大，至少不偏
    mixed: cfgs.length > 1 && new Set(
      cfgs.map((c) => resolveScenarioId(c.kind, c.scenario)),
    ).size > 1,
    vuIsPlanned: false,
  }
})

// load 图②：实测 并发(VU) × 延迟(p95) 按时间戳最近匹配 → (VU, RT) 散点。
// 参考 ConcurrencyRpsChart 的 vu×rps 对齐：rps/vu 来自不同源，时间戳常差 < 2s。
function computeRtScatter(vu: SeriesPoint[], lat: SeriesPoint[]): { x: number; y: number }[] {
  if (!vu.length || !lat.length) return []
  const NEAR_MS = 2000
  const out: { x: number; y: number }[] = []
  let j = 0
  for (const [t, rt] of lat) {
    while (j + 1 < vu.length && Math.abs(vu[j + 1][0] - t) <= Math.abs(vu[j][0] - t)) j++
    const [vt, v] = vu[j]
    if (v <= 0 || Math.abs(vt - t) > NEAR_MS) continue
    out.push({ x: v, y: rt })
  }
  return out
}

// 真实模式：把当前场景的 ctx + 取数结果组装成 ScenarioPair 吃的 spec 形状。
// 混合场景 (mixed) 返回 null → 模板退到单张兜底散点图。
const realSpec = computed<ScenarioMockSpec | null>(() => {
  const c = ctx.value
  if (!c || c.mixed) return null
  const sc = c.scenario
  return {
    id: sc.id, label: sc.label, color: sc.color, kind: sc.kind,
    rps: c.rps, vu: c.vu, lat: c.lat,
    targetRpsPerSec: c.targetRpsPerSec,
    rtScatter: sc.id === 'load' ? computeRtScatter(c.vu, c.lat) : undefined,
    samplerStats: sc.id === 'throughput' ? (props.samplerStats ?? []) : undefined,
    baselineVersions: sc.id === 'baseline' ? (props.baselineCompare ?? undefined) : undefined,
    // errorBuckets/memoryLeak/queueDepth 不填 → stress 真实自取 / soak·spike 空态占位
  }
})

// mock 模式下选中具体场景（selectedTg = 场景 label）→ 取对应 spec 渲染单卡
const mockSelectedSpec = computed<ScenarioMockSpec | null>(() => {
  if (!props.mockMode || !props.selectedTg) return null
  return (props.mockScenarios || []).find((s) => s.label === props.selectedTg) ?? null
})
</script>

<template>
  <!-- mock 预览分发：选中场景 → 单卡 2 图；全部 → 6 场景画廊 -->
  <template v-if="mockMode">
    <ScenarioPair
      v-if="mockSelectedSpec"
      :spec="mockSelectedSpec"
      :x-range="mockXRange ?? null"
      :is-dark="isDark"
      :show-header="false"
    />
    <div v-else class="space-y-5">
      <ScenarioPair
        v-for="s in (mockScenarios || [])"
        :key="s.id"
        :spec="s"
        :x-range="mockXRange ?? null"
        :is-dark="isDark"
      />
    </div>
  </template>

  <!-- 真实分发：同质场景 → 图① + 图② 两栏（ScenarioPair）；混合/无信息 → 单张兜底 -->
  <div v-else class="flex flex-col h-full">
    <div
      v-if="ctx?.mixed"
      class="text-[10.5px] px-2 py-1 mb-1 rounded"
      :style="{
        background: isDark ? 'rgba(245,158,11,0.1)' : 'rgba(245,158,11,0.08)',
        color: '#f59e0b',
      }"
    >
      多 TG 场景混合，末位图退到通用散点；切到具体 TG 查看对应场景图。
    </div>
    <!-- 同质场景：2 图 -->
    <ScenarioPair
      v-if="realSpec"
      :spec="realSpec"
      :run-id="runId ?? null"
      :is-terminal="isTerminal ?? false"
      :x-range="xRange ?? null"
      :is-dark="isDark"
      :show-header="false"
    />
    <!-- 混合 / 无 ctx：退到单张散点图 -->
    <div v-else class="flex-1 min-h-0">
      <ConcurrencyRpsChart :rps="rps" :vu="vu" :is-dark="isDark" />
    </div>
  </div>
</template>
