<script setup lang="ts">
import { computed } from 'vue'
import type {
  RunMetricsSeries, RunMetricsTotals, Task, TaskRun,
} from '@/types/task'
import { fmtBytesTotal, fmtInt, statsOf } from './chartFactory'
import { colorForErrorMetric, SEMANTIC } from './semanticColors'
import { scenarioById, inferScenarioFromKind } from '@/components/tasks/configStageCtx'

// 单行紧凑：TG 切换 chip 组 + 累计 chips + 整体 RPS / P95。
// 场景徽章已搬到 RunPlanSummary（进度条下方）；KpiBar 不再展示场景，避免重复。
// 错误率（累计 + 60s）放在下面"总错误"卡片标题里，KpiBar 不再展示百分比。
const props = defineProps<{
  task: Task | null
  run: TaskRun | null
  totals: RunMetricsTotals | null     // 已是 selectedTg 过滤后的（父组件 effectiveTotals）
  series: RunMetricsSeries | null     // 已是 selectedTg 过滤后的（父组件 effectiveOverall）
  tgKeys: string[]                    // 全部 TG / sample label 列表（来自 metrics.by_tg keys）
  selectedTg: string | null           // 当前选中；null = 全部
  isDark: boolean
}>()
const emit = defineEmits<{
  (e: 'update:selectedTg', v: string | null): void
}>()

// 平均 RPS / 整体 P95 直接用 statsOf 的 mean，跟趋势图右侧 stats 对齐口径。
// 不再用 total_count / 总时长——那会把 ramp / shutdown 的 0 点稀释进去，跟图里 mean 对不上。
const overallRps = computed<number | null>(() => {
  const pts = props.series?.rps
  if (!pts?.length) return null
  return statsOf(pts).mean
})

const overallP95 = computed<number | null>(() => {
  const pts = props.series?.p95_ms
  if (!pts?.length) return null
  return statsOf(pts).mean
})

const muted = computed(() => props.isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.55)')

// 主场景徽章：run 快照优先，回退当前 task 配置；第一个 TG 为主场景，多 TG 附 +N。
// （上一轮从 RunPlanSummary 信息条移除，闭环到 KpiBar 这里。）
const scenarioCfgs = computed(() => {
  const snap = props.run?.thread_groups_config_snapshot
  if (snap && snap.length) return snap
  return props.task?.thread_groups_config || []
})
const primaryScenario = computed(() => {
  const first = scenarioCfgs.value[0]
  if (!first) return null
  return scenarioById(first.scenario || inferScenarioFromKind(first.kind))
})
const scenarioExtraN = computed(() => Math.max(0, scenarioCfgs.value.length - 1))

interface Chip { label: string; color: string; title?: string }

// 始终渲染（没数据时显示 0 / —），避免新任务进来 KPI 行空荡荡。
const chips = computed<Chip[]>(() => {
  const t = props.totals
  return [
    { label: `${fmtInt(t?.total_count ?? 0)} req`, color: muted.value },
    {
      label: `${fmtInt(t?.total_errors ?? 0)} fail`,
      color: colorForErrorMetric(t?.total_errors ?? 0, muted.value),
    },
    { label: `${fmtBytesTotal(t?.total_bytes_recv ?? 0)} ↓`, color: muted.value },
    { label: `${fmtBytesTotal(t?.total_bytes_sent ?? 0)} ↑`, color: muted.value },
    { label: `平均 RPS ${(overallRps.value ?? 0).toFixed(1)}`, color: SEMANTIC.traffic },
    {
      label: overallP95.value != null ? `整体 P95 ${Math.round(overallP95.value)} ms` : '整体 P95 —',
      color: muted.value,
      title: '所有时序点的 P95 中位数',
    },
  ]
})
</script>

<template>
  <div
    class="flex items-center flex-wrap gap-x-3 gap-y-1 px-1"
  >
    <!-- 主场景徽章（单 TG 即唯一场景；多 TG = 主场景 + N，切换仍按 TG）-->
    <span
      v-if="primaryScenario"
      class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] flex-shrink-0 cursor-default"
      :style="{
        background: `${primaryScenario.color}1f`,
        color: primaryScenario.color,
        border: `1px solid ${primaryScenario.color}33`,
      }"
    >
      <component :is="primaryScenario.icon" :size="11" />
      {{ primaryScenario.label }}
      <span v-if="scenarioExtraN > 0" class="opacity-60 ml-0.5">+{{ scenarioExtraN }}</span>
    </span>

    <!-- 多 TG 切换 chip 组：tgKeys.length > 1 时显示；点击切换 selectedTg。
         单 TG / 无 TG 时不渲染 chip 组（TrendsLayout 已自动把 selectedTg 设为该
         唯一 TG，"全部"按钮没意义）。chip key 是 ThreadGroup testname（per-TG listener
         注入 TAG_thread_group，InfluxDB GROUP BY 切的就是这个 tag）。 -->
    <template v-if="tgKeys.length > 1">
      <button
        type="button"
        class="text-[10.5px] px-1.5 py-0.5 rounded cursor-pointer transition-colors flex-shrink-0"
        :style="{
          color: selectedTg === null
            ? (isDark ? 'rgba(255,255,255,0.9)' : 'rgba(0,0,0,0.85)')
            : muted,
          background: selectedTg === null
            ? (isDark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.08)')
            : (isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)'),
          border: `1px solid ${
            selectedTg === null
              ? (isDark ? 'rgba(255,255,255,0.18)' : 'rgba(0,0,0,0.15)')
              : 'transparent'
          }`,
        }"
        title="所有线程组合计"
        @click="emit('update:selectedTg', null)"
      >全部</button>
      <button
        v-for="key in tgKeys"
        :key="key"
        type="button"
        class="text-[10.5px] px-1.5 py-0.5 rounded cursor-pointer transition-colors max-w-[140px] truncate flex-shrink-0"
        :style="{
          color: selectedTg === key
            ? (isDark ? 'rgba(255,255,255,0.9)' : 'rgba(0,0,0,0.85)')
            : muted,
          background: selectedTg === key
            ? (isDark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.08)')
            : (isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)'),
          border: `1px solid ${
            selectedTg === key
              ? (isDark ? 'rgba(255,255,255,0.18)' : 'rgba(0,0,0,0.15)')
              : 'transparent'
          }`,
        }"
        :title="`只看：${key}`"
        @click="emit('update:selectedTg', key)"
      >{{ key }}</button>
    </template>

    <span class="text-[10.5px] tracking-wide opacity-70" :style="{ color: muted }">累计</span>

    <span
      v-for="(c, i) in chips"
      :key="i"
      class="text-[11.5px] tabular-nums"
      :style="{ color: c.color }"
      :title="c.title"
    >{{ c.label }}</span>

    <span class="text-[10px] ml-auto opacity-50" :style="{ color: muted }">
      基于 InfluxDB（终态后以 JTL 为准）
    </span>
  </div>
</template>
