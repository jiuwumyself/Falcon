<script setup lang="ts">
import { computed } from 'vue'
import type {
  RunMetricsSeries, ScenarioId, SeriesPoint, Task, TGKind,
} from '@/types/task'
import {
  scenarioById, inferScenarioFromKind, type ScenarioDef,
} from './scenarioCtx'
import ConcurrencyRpsChart from './ConcurrencyRpsChart.vue'
import ErrorBreakdownStackedChart from './ErrorBreakdownStackedChart.vue'
import VuRpsDualAxisChart from './VuRpsDualAxisChart.vue'
import TargetRpsVsActualChart from './TargetRpsVsActualChart.vue'

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
//   stress     → ErrorBreakdownStackedChart (5 桶堆叠：错误类型转移)
//   soak       → ConcurrencyRpsChart (showTrendLine：抖动 + 线性回归漂移)
//   spike      → VuRpsDualAxisChart (双轴时序：VU/RPS 跟随)
//   throughput → TargetRpsVsActualChart (目标 vs 实际)
const props = defineProps<{
  task: Task
  selectedTg: string | null
  // 全部模式 (selectedTg=null) 的合计 rps/vu
  rps: SeriesPoint[]
  vu: SeriesPoint[]
  // 单 TG 选中时切片来源（key = TG testname）
  byTg: Record<string, RunMetricsSeries>
  // 后端按 testname 给的 {kind, params, scenario}
  tgPlannedMeta: Record<string, { kind: TGKind; params: Record<string, any>; scenario?: ScenarioId | null }>
  // sampler→[TG name 列表] 映射；throughput 场景下要 × samplers_per_TG 把
  // arrivals/sec 换算成可跟 actual rps 对比的 samples/sec
  samplerThreadGroup?: Record<string, string[]>
  runId: string | null
  isTerminal: boolean
  xRange?: [number, number] | null
  isDark: boolean
}>()

interface ResolvedCtx {
  scenario: ScenarioDef
  rps: SeriesPoint[]
  vu: SeriesPoint[]
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
        targetRpsPerSec: targetRpsFromParams(id, meta.params, countSamplersInTg(props.selectedTg, props.samplerThreadGroup)),
        mixed: false,
        vuIsPlanned: useFallbackVu,
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
    targetRpsPerSec: targetRpsFromParams(id, cfg.params || {}, 0),  // 老 run 无 metrics 时不放大，至少不偏
    mixed: cfgs.length > 1 && new Set(
      cfgs.map((c) => resolveScenarioId(c.kind, c.scenario)),
    ).size > 1,
    vuIsPlanned: false,
  }
})

const usesConcurrencyChart = computed(() =>
  ctx.value && ['baseline', 'load', 'soak'].includes(ctx.value.scenario.id),
)
const showTrendLine = computed(() => ctx.value?.scenario.id === 'soak')
</script>

<template>
  <div class="flex flex-col h-full">
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
    <div class="flex-1 min-h-0">
      <ConcurrencyRpsChart
        v-if="ctx && usesConcurrencyChart"
        :rps="ctx.rps"
        :vu="ctx.vu"
        :show-trend-line="showTrendLine"
        :is-dark="isDark"
      />
      <ErrorBreakdownStackedChart
        v-else-if="ctx?.scenario.id === 'stress'"
        :run-id="runId"
        :is-terminal="isTerminal"
        :x-range="xRange ?? null"
        :is-dark="isDark"
      />
      <VuRpsDualAxisChart
        v-else-if="ctx?.scenario.id === 'spike'"
        :rps="ctx.rps"
        :vu="ctx.vu"
        :vu-is-planned="ctx.vuIsPlanned"
        :x-range="xRange ?? null"
        :is-dark="isDark"
      />
      <TargetRpsVsActualChart
        v-else-if="ctx?.scenario.id === 'throughput'"
        :rps="ctx.rps"
        :target-rps-per-sec="ctx.targetRpsPerSec"
        :x-range="xRange ?? null"
        :is-dark="isDark"
      />
      <!-- 兜底：没有任何 ctx 信息时退到散点图（不传 vu/rps 时图自处理空态）-->
      <ConcurrencyRpsChart
        v-else
        :rps="rps"
        :vu="vu"
        :is-dark="isDark"
      />
    </div>
  </div>
</template>
