<script setup lang="ts">
import { computed } from 'vue'
import type { SeriesPoint, Task, ThreadGroupConfig } from '@/types/task'
import {
  scenarioById, inferScenarioFromKind, type ScenarioDef,
} from './scenarioCtx'
import ConcurrencyRpsChart from './ConcurrencyRpsChart.vue'
import ErrorBreakdownStackedChart from './ErrorBreakdownStackedChart.vue'
import VuRpsDualAxisChart from './VuRpsDualAxisChart.vue'
import TargetRpsVsActualChart from './TargetRpsVsActualChart.vue'

// 末位「场景上下文图」容器：按当前选中 TG（或第一个 TG）解析场景 → 渲染对应图。
//
// 多 TG 联动：当 selectedTg 非空时，按该 TG 的 scenario 选图；为空（合计模式）
// 走 thread_groups_config[0]。这样在 KpiBar 切 TG 时末位图跟着切。
//
// 场景 → 图映射：
//   baseline   → ConcurrencyRpsChart (isFlatVu 分支自动触发 RPS 抖动模式)
//   load       → ConcurrencyRpsChart (非 flat 散点：看拐点)
//   stress     → ErrorBreakdownStackedChart (5 桶堆叠：看错误类型转移)
//   soak       → ConcurrencyRpsChart (showTrendLine：抖动 + 线性回归漂移)
//   spike      → VuRpsDualAxisChart (双轴时序：看 VU/RPS 跟随)
//   throughput → TargetRpsVsActualChart (目标线对比)
const props = defineProps<{
  task: Task
  selectedTg: string | null
  rps: SeriesPoint[]
  vu: SeriesPoint[]
  runId: string | null
  isTerminal: boolean
  xRange?: [number, number] | null
  isDark: boolean
}>()

// 通过 selectedTg（TG 名 = testname）反向找配置项
function findTgConfig(): ThreadGroupConfig | null {
  const cfgs = props.task.thread_groups_config || []
  if (!cfgs.length) return null
  if (props.selectedTg) {
    // selectedTg 是 testname；task.thread_groups_config 里只有 path/kind/params/scenario
    // 没存 testname。最稳妥的兜底：当多 TG 时，selectedTg 选中后我们走"按场景排第几个"
    // 的近似匹配——但 testname 和 path 没有直接映射。
    // 退而求其次：单 TG 直接用第一项；多 TG 时如果 selectedTg 命中某个 cfg 的 testname
    // （某些 run 里前端会同步），优先用；否则用第一项兜底。
    const matched = cfgs.find((c) => (c.params as any)?.testname === props.selectedTg)
    if (matched) return matched
  }
  return cfgs[0]
}

const currentScenario = computed<ScenarioDef | null>(() => {
  const cfg = findTgConfig()
  if (!cfg) return null
  const id = cfg.scenario ?? inferScenarioFromKind(cfg.kind)
  return scenarioById(id)
})

// throughput 场景：从配置算出 per-sec 目标 RPS（unit 'M' → /60）
const targetRpsPerSec = computed<number | null>(() => {
  const cfg = findTgConfig()
  if (!cfg) return null
  if (currentScenario.value?.id !== 'throughput') return null
  const target = Number(cfg.params?.target_rps ?? 0)
  if (!target || target <= 0) return null
  const unit = (cfg.params?.unit as string) === 'M' ? 60 : 1
  return target / unit
})

// 走 ConcurrencyRpsChart 的场景列表（baseline / load / soak）
const usesConcurrencyChart = computed(() =>
  currentScenario.value && ['baseline', 'load', 'soak'].includes(currentScenario.value.id),
)
// soak 才开启回归线
const showTrendLine = computed(() => currentScenario.value?.id === 'soak')
</script>

<template>
  <div class="flex flex-col h-full">
    <ConcurrencyRpsChart
      v-if="usesConcurrencyChart"
      :rps="rps"
      :vu="vu"
      :show-trend-line="showTrendLine"
      :is-dark="isDark"
    />
    <ErrorBreakdownStackedChart
      v-else-if="currentScenario?.id === 'stress'"
      :run-id="runId"
      :is-terminal="isTerminal"
      :x-range="xRange ?? null"
      :is-dark="isDark"
    />
    <VuRpsDualAxisChart
      v-else-if="currentScenario?.id === 'spike'"
      :rps="rps"
      :vu="vu"
      :x-range="xRange ?? null"
      :is-dark="isDark"
    />
    <TargetRpsVsActualChart
      v-else-if="currentScenario?.id === 'throughput'"
      :rps="rps"
      :target-rps-per-sec="targetRpsPerSec"
      :x-range="xRange ?? null"
      :is-dark="isDark"
    />
    <!-- 兜底：没有 scenario 信息时退到散点图 -->
    <ConcurrencyRpsChart
      v-else
      :rps="rps"
      :vu="vu"
      :is-dark="isDark"
    />
  </div>
</template>
