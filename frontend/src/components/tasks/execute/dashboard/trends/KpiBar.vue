<script setup lang="ts">
import { computed } from 'vue'
import type {
  RunMetricsSeries, RunMetricsTotals, SeriesPoint, Task,
} from '@/types/task'
import { fmtBytesTotal, fmtInt } from './chartFactory'
import { colorForErrorMetric, colorForErrorRate, SEMANTIC } from './semanticColors'
import { pickPrimaryScenario, extraScenarioCount, listScenarios } from './scenarioCtx'

// 三段结构（Tufte 视觉重力 = 字号 + 空间）：
//   ① 顶部场景徽章 chip（icon + label + 14% 透明度场景色）
//   ② 主级（36px 巨字号）：错误率 + P95
//   ③ 副级（24px）：RPS + 现在并发
//   ④ 累计带（12px 单行）：5,138 req · 642 fail · 32 MB ↓ · 38 MB ↑
const props = defineProps<{
  task: Task | null
  totals: RunMetricsTotals | null
  series: RunMetricsSeries | null
  isDark: boolean
}>()

function lastOf(pts: SeriesPoint[] | undefined): number | null {
  if (!pts || !pts.length) return null
  return pts[pts.length - 1][1]
}

// 实时错误率：60s 滚动窗口（与 ErrorRateGauge 同算法）
function lastWindowRate(
  errorPts: SeriesPoint[] | undefined,
  rpsPts: SeriesPoint[] | undefined,
  windowMs = 60_000,
): number | null {
  if (!errorPts?.length || !rpsPts?.length) return null
  const now = Math.max(
    errorPts[errorPts.length - 1][0],
    rpsPts[rpsPts.length - 1][0],
  )
  const cutoff = now - windowMs
  let errSum = 0
  let reqSum = 0
  for (const [t, v] of errorPts) if (t >= cutoff) errSum += v
  for (const [t, v] of rpsPts) if (t >= cutoff) reqSum += v
  if (reqSum === 0) return null
  return (errSum / reqSum) * 100
}

const primary = computed(() => props.isDark ? 'rgba(255,255,255,0.92)' : 'rgba(0,0,0,0.85)')
const muted = computed(() => props.isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.55)')

// ── 主场景徽章 ────────────────────────────────────────────────
const scenario = computed(() => pickPrimaryScenario(props.task))
const extraN = computed(() => extraScenarioCount(props.task))
const allScenarioLabels = computed(
  () => listScenarios(props.task).map((s) => s.label).join(' / '),
)

// ── 主级 + 副级数字 ──────────────────────────────────────────
const errorPct = computed(() =>
  lastWindowRate(props.series?.error_count, props.series?.rps),
)
const errorPctText = computed(() =>
  errorPct.value === null ? '—' : `${errorPct.value.toFixed(2)}%`,
)
const errorPctColor = computed(() =>
  errorPct.value === null ? muted.value : colorForErrorRate(errorPct.value),
)

const p95 = computed(() => lastOf(props.series?.p95_ms))
const p95Text = computed(() => p95.value === null ? '—' : `${Math.round(p95.value)} ms`)

const rps = computed(() => lastOf(props.series?.rps))
const rpsText = computed(() => rps.value === null ? '—' : rps.value.toFixed(1))

const vu = computed(() => lastOf(props.series?.active_users))
const vuText = computed(() => vu.value === null ? '—' : `${Math.round(vu.value)}`)

// ── 累计折一行 ────────────────────────────────────────────────
const cumulativeChips = computed(() => {
  const t = props.totals
  const totalCount = t?.total_count ?? 0
  const totalErrors = t?.total_errors ?? 0
  const recv = t?.total_bytes_recv ?? 0
  const sent = t?.total_bytes_sent ?? 0
  return [
    { label: `${fmtInt(totalCount)} req`, color: muted.value },
    {
      label: `${fmtInt(totalErrors)} fail`,
      color: colorForErrorMetric(totalErrors, muted.value),
    },
    { label: `${fmtBytesTotal(recv)} ↓`, color: muted.value },
    { label: `${fmtBytesTotal(sent)} ↑`, color: muted.value },
  ]
})

// ── 卡片样式 ──────────────────────────────────────────────────
const heroCardStyle = computed(() => ({
  background: props.isDark ? 'rgba(255,255,255,0.025)' : 'rgba(255,255,255,0.78)',
  border: props.isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.06)',
}))
const subCardStyle = computed(() => ({
  background: props.isDark ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.65)',
  border: props.isDark ? '1px solid rgba(255,255,255,0.05)' : '1px solid rgba(0,0,0,0.05)',
}))
</script>

<template>
  <div class="flex flex-col gap-2">
    <!-- ① 场景徽章（task null / 推断失败时不显示）-->
    <div v-if="scenario" class="flex items-center gap-1.5">
      <span
        class="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-[11.5px]"
        :style="{
          background: `${scenario.color}24`,
          color: scenario.color,
          border: `1px solid ${scenario.color}40`,
        }"
      >
        <component :is="scenario.icon" :size="13" />
        {{ scenario.label }}
      </span>
      <span
        v-if="extraN > 0"
        class="text-[10.5px] px-1.5 py-0.5 rounded"
        :title="`全部 TG 场景：${allScenarioLabels}`"
        :style="{
          color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)',
          background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)',
        }"
      >
        +{{ extraN }} 个 TG
      </span>
    </div>

    <!-- ② 主级巨字号：错误率 + P95（grid-cols-2） -->
    <div class="grid grid-cols-2 gap-3">
      <div class="rounded-xl px-5 py-3 flex flex-col items-center justify-center"
           :style="heroCardStyle">
        <div class="text-[11px] tracking-wide mb-1.5" :style="{ color: muted }">
          实时错误率（60s 窗口）
        </div>
        <div
          class="text-[36px] font-semibold leading-none tabular-nums"
          :style="{ color: errorPctColor }"
        >{{ errorPctText }}</div>
      </div>
      <div class="rounded-xl px-5 py-3 flex flex-col items-center justify-center"
           :style="heroCardStyle">
        <div class="text-[11px] tracking-wide mb-1.5" :style="{ color: muted }">
          P95 延迟
        </div>
        <div
          class="text-[36px] font-semibold leading-none tabular-nums"
          :style="{ color: primary }"
        >{{ p95Text }}</div>
      </div>
    </div>

    <!-- ③ 副级：RPS + 现在并发（grid-cols-2） -->
    <div class="grid grid-cols-2 gap-3">
      <div class="rounded-xl px-4 py-2 flex items-center justify-between"
           :style="subCardStyle">
        <span class="text-[11px]" :style="{ color: muted }">RPS</span>
        <span class="text-[22px] font-semibold leading-none tabular-nums"
              :style="{ color: SEMANTIC.traffic }">{{ rpsText }}</span>
      </div>
      <div class="rounded-xl px-4 py-2 flex items-center justify-between"
           :style="subCardStyle">
        <span class="text-[11px]" :style="{ color: muted }">现在并发</span>
        <span class="text-[22px] font-semibold leading-none tabular-nums"
              :style="{ color: SEMANTIC.saturation }">{{ vuText }}</span>
      </div>
    </div>

    <!-- ④ 累计带：折成一行小字 chip -->
    <div class="flex items-center flex-wrap gap-x-3 gap-y-1 px-1 pt-1">
      <span class="text-[10.5px] tracking-wide" :style="{ color: muted, opacity: 0.7 }">累计</span>
      <span
        v-for="(c, i) in cumulativeChips"
        :key="i"
        class="text-[11.5px] tabular-nums"
        :style="{ color: c.color }"
      >{{ c.label }}</span>
      <span class="text-[10px] ml-auto" :style="{ color: muted, opacity: 0.5 }">
        基于 InfluxDB 实时聚合（终态后以 JTL 为准）
      </span>
    </div>
  </div>
</template>
