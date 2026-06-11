<script setup lang="ts">
// 单个线程组(TG)的报告卡：混合压测里每个 TG 一张，问题 TG 置顶展开、正常 TG 折叠。
// 折叠态 = 卡头摘要行；展开态 = 该 TG 的结论 + 容量拐点 + 红黑榜 + 接口 RT 图 + 错误代表。
import { computed } from 'vue'
import { ChevronDown, ChevronRight, Timer, AlertOctagon, Activity } from 'lucide-vue-next'
import type { SamplerStat, ErrorAggregateRow, SeriesPoint } from '@/types/task'
import { SEMANTIC } from '@/components/tasks/execute/dashboard/trends/semanticColors'
import ConcurrencyRpsChart from '@/components/tasks/execute/dashboard/trends/ConcurrencyRpsChart.vue'
import SoakLatencyTrendChart from '@/components/tasks/execute/dashboard/trends/SoakLatencyTrendChart.vue'
import VuRpsDualAxisChart from '@/components/tasks/execute/dashboard/trends/VuRpsDualAxisChart.vue'
import TargetRpsVsActualChart from '@/components/tasks/execute/dashboard/trends/TargetRpsVsActualChart.vue'
import SamplerRtRangeChart from '@/components/tasks/execute/dashboard/trends/SamplerRtRangeChart.vue'

type Health = 'critical' | 'warn' | 'ok'

const props = defineProps<{
  tgName: string
  scenario: { id: string; label: string; color: string } | null
  health: Health
  summary: { errorRate: number; p99: number; peakRps: number | null; peakConcurrency: number | null; totalRequests: number }
  rps: SeriesPoint[]
  vu: SeriesPoint[]
  lat: SeriesPoint[]
  targetRpsPerSec: number | null
  samplers: SamplerStat[]
  errorRows: ErrorAggregateRow[]
  narrative: string[]
  expanded: boolean
  isDark: boolean
}>()

// 场景 → 主图分发（与 Step 3 ScenarioContextChart 一致）：
//   baseline/load/stress → 并发-吞吐拐点；soak → 延迟泄漏趋势；
//   spike → VU/RPS 双轴跟随；throughput → 目标 vs 实际 RPS。
const usesConcurrency = computed(() =>
  !props.scenario || ['baseline', 'load', 'stress'].includes(props.scenario.id))
const chartTitle = computed(() => {
  const id = props.scenario?.id
  if (id === 'soak') return '延迟趋势（p95 + 回归线，抓泄漏）'
  if (id === 'spike') return 'VU / RPS 双轴跟随'
  if (id === 'throughput') return '目标 vs 实际 RPS'
  return '并发-吞吐关系（自动标拐点）'
})
const emit = defineEmits<{ (e: 'toggle'): void }>()
const d = (l: string, dk: string) => (props.isDark ? dk : l)

const HEALTH_META: Record<Health, { label: string; color: string }> = {
  critical: { label: '严重', color: SEMANTIC.errors },
  warn: { label: '关注', color: SEMANTIC.latency },
  ok: { label: '正常', color: SEMANTIC.success },
}
const hm = computed(() => HEALTH_META[props.health])

const slowest = computed(() =>
  [...props.samplers].filter((s) => s.label !== 'all').sort((a, b) => b.p99_ms - a.p99_ms).slice(0, 5))
const mostErrors = computed(() =>
  props.samplers.filter((s) => s.label !== 'all' && s.error > 0).sort((a, b) => b.error - a.error).slice(0, 5))
const rtStats = computed(() => props.samplers.filter((s) => s.label !== 'all'))

function fmtMs(v: number) { return v >= 1000 ? (v / 1000).toFixed(2) + 's' : Math.round(v) + 'ms' }
function fmtNum(v: number) { return v >= 10000 ? (v / 1000).toFixed(1) + 'k' : String(v) }

const card = computed(() => ({
  background: props.isDark ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.6)',
  border: `1px solid ${props.expanded ? hm.value.color + '50' : props.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
}))
</script>

<template>
  <div class="rounded-xl overflow-hidden" :style="card">
    <!-- 卡头：点击折叠/展开。左侧健康色条 -->
    <button class="w-full flex items-center gap-2.5 px-3 py-2.5 text-left" @click="emit('toggle')">
      <span class="w-1 self-stretch rounded-full flex-shrink-0" :style="{ background: hm.color }" />
      <component :is="expanded ? ChevronDown : ChevronRight" :size="14" :color="d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)')" class="flex-shrink-0" />
      <span class="text-[13px] font-semibold flex-shrink-0" :style="{ color: d('#1a1a2e', '#fff') }">{{ tgName }}</span>
      <span v-if="scenario" class="text-[10px] px-1.5 py-0.5 rounded flex-shrink-0"
            :style="{ background: scenario.color + '1f', color: scenario.color }">{{ scenario.label }}</span>
      <span class="text-[10px] px-1.5 py-0.5 rounded flex-shrink-0 font-medium"
            :style="{ background: hm.color + '1f', color: hm.color }">{{ hm.label }}</span>

      <!-- 折叠态摘要指标（展开时藏，避免与下方重复）-->
      <template v-if="!expanded">
        <span class="flex-1" />
        <span class="text-[11px] tabular-nums flex items-center gap-3" :style="{ color: d('rgba(0,0,0,0.55)', 'rgba(255,255,255,0.55)') }">
          <span :style="{ color: summary.errorRate >= 1 ? SEMANTIC.errors : 'inherit' }">错 {{ summary.errorRate.toFixed(2) }}%</span>
          <span>P99 {{ fmtMs(summary.p99) }}</span>
          <span v-if="summary.peakRps != null" class="hidden sm:inline">{{ summary.peakRps.toFixed(0) }} req/s</span>
          <span v-if="summary.peakConcurrency != null" class="hidden md:inline">{{ summary.peakConcurrency }} VU</span>
        </span>
      </template>
      <span v-else class="flex-1" />
    </button>

    <!-- 展开内容 -->
    <div v-if="expanded" class="px-3 pb-3 space-y-3">
      <!-- 结论 -->
      <ul v-if="narrative.length" class="space-y-1 m-0 pl-0 list-none">
        <li v-for="(line, i) in narrative" :key="i" class="text-[12px] leading-relaxed flex gap-1.5"
            :style="{ color: d('rgba(0,0,0,0.72)', 'rgba(255,255,255,0.75)') }">
          <span :style="{ color: hm.color }">·</span><span>{{ line }}</span>
        </li>
      </ul>

      <!-- KPI 行 -->
      <div class="grid grid-cols-4 gap-2">
        <div class="p-2 rounded-lg" :style="{ background: d('rgba(0,0,0,0.03)', 'rgba(255,255,255,0.03)') }">
          <p class="text-[10px] m-0" :style="{ color: d('rgba(0,0,0,0.45)', 'rgba(255,255,255,0.45)') }">总请求</p>
          <p class="text-[15px] font-semibold m-0 tabular-nums" :style="{ color: d('#1a1a2e', '#fff') }">{{ fmtNum(summary.totalRequests) }}</p>
        </div>
        <div class="p-2 rounded-lg" :style="{ background: d('rgba(0,0,0,0.03)', 'rgba(255,255,255,0.03)') }">
          <p class="text-[10px] m-0" :style="{ color: d('rgba(0,0,0,0.45)', 'rgba(255,255,255,0.45)') }">峰值 RPS</p>
          <p class="text-[15px] font-semibold m-0 tabular-nums" :style="{ color: d('#1a1a2e', '#fff') }">{{ summary.peakRps != null ? summary.peakRps.toFixed(0) : '—' }}</p>
        </div>
        <div class="p-2 rounded-lg" :style="{ background: d('rgba(0,0,0,0.03)', 'rgba(255,255,255,0.03)') }">
          <p class="text-[10px] m-0" :style="{ color: d('rgba(0,0,0,0.45)', 'rgba(255,255,255,0.45)') }">P99</p>
          <p class="text-[15px] font-semibold m-0 tabular-nums" :style="{ color: d('#1a1a2e', '#fff') }">{{ fmtMs(summary.p99) }}</p>
        </div>
        <div class="p-2 rounded-lg" :style="{ background: d('rgba(0,0,0,0.03)', 'rgba(255,255,255,0.03)') }">
          <p class="text-[10px] m-0" :style="{ color: d('rgba(0,0,0,0.45)', 'rgba(255,255,255,0.45)') }">错误率</p>
          <p class="text-[15px] font-semibold m-0 tabular-nums" :style="{ color: summary.errorRate >= 1 ? SEMANTIC.errors : d('#1a1a2e', '#fff') }">{{ summary.errorRate.toFixed(2) }}%</p>
        </div>
      </div>

      <!-- 场景主图（按 TG 场景分发：基准/负载/压力→拐点；稳定性→泄漏；峰值→双轴；吞吐量→目标vs实际）-->
      <div>
        <p class="text-[11px] mb-1 flex items-center gap-1.5" :style="{ color: d('rgba(0,0,0,0.55)', 'rgba(255,255,255,0.55)') }">
          <Activity :size="12" :color="SEMANTIC.saturation" />{{ chartTitle }}
        </p>
        <div style="height:200px">
          <ConcurrencyRpsChart v-if="usesConcurrency" :rps="rps" :vu="vu" :is-dark="isDark" />
          <SoakLatencyTrendChart v-else-if="scenario?.id === 'soak'" :lat="lat" :x-range="null" :is-dark="isDark" />
          <VuRpsDualAxisChart v-else-if="scenario?.id === 'spike'" :rps="rps" :vu="vu" :x-range="null" :is-dark="isDark" />
          <TargetRpsVsActualChart v-else-if="scenario?.id === 'throughput'" :rps="rps" :target-rps-per-sec="targetRpsPerSec" :x-range="null" :is-dark="isDark" />
        </div>
      </div>

      <!-- 红黑榜 -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <p class="text-[11px] mb-1 flex items-center gap-1.5" :style="{ color: d('rgba(0,0,0,0.55)', 'rgba(255,255,255,0.55)') }">
            <Timer :size="12" :color="SEMANTIC.latency" />最慢接口
          </p>
          <p v-if="!slowest.length" class="text-[11px] py-2" :style="{ color: d('rgba(0,0,0,0.35)', 'rgba(255,255,255,0.35)') }">无接口数据</p>
          <div v-for="s in slowest" :key="s.label" class="flex items-center gap-2 py-0.5 text-[11px]">
            <span class="flex-1 min-w-0 truncate" :style="{ color: d('rgba(0,0,0,0.75)', 'rgba(255,255,255,0.75)') }" :title="s.label">{{ s.label }}</span>
            <span class="tabular-nums font-medium" :style="{ color: s.p99_ms >= 1000 ? SEMANTIC.errors : d('#1a1a2e', '#fff') }">{{ fmtMs(s.p99_ms) }}</span>
          </div>
        </div>
        <div>
          <p class="text-[11px] mb-1 flex items-center gap-1.5" :style="{ color: d('rgba(0,0,0,0.55)', 'rgba(255,255,255,0.55)') }">
            <AlertOctagon :size="12" :color="SEMANTIC.errors" />报错最多接口
          </p>
          <p v-if="!mostErrors.length" class="text-[11px] py-2" :style="{ color: d('rgba(0,0,0,0.35)', 'rgba(255,255,255,0.35)') }">无失败接口 🎉</p>
          <div v-for="s in mostErrors" :key="s.label" class="flex items-center gap-2 py-0.5 text-[11px]">
            <span class="flex-1 min-w-0 truncate" :style="{ color: d('rgba(0,0,0,0.75)', 'rgba(255,255,255,0.75)') }" :title="s.label">{{ s.label }}</span>
            <span class="tabular-nums font-medium" :style="{ color: SEMANTIC.errors }">×{{ s.error }}</span>
          </div>
        </div>
      </div>

      <!-- 接口 RT 分布 -->
      <div v-if="rtStats.length">
        <p class="text-[11px] mb-1 flex items-center gap-1.5" :style="{ color: d('rgba(0,0,0,0.55)', 'rgba(255,255,255,0.55)') }">
          <Activity :size="12" :color="SEMANTIC.latency" />接口响应时间分布（min / avg / p99）
        </p>
        <div :style="{ height: `${Math.max(120, Math.min(rtStats.length, 10) * 24 + 36)}px` }">
          <SamplerRtRangeChart :stats="rtStats" :is-dark="isDark" />
        </div>
      </div>

      <!-- 错误代表 -->
      <div v-if="errorRows.length">
        <p class="text-[11px] mb-1" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">代表错误</p>
        <div v-for="(e, i) in errorRows.slice(0, 5)" :key="i" class="flex items-start gap-2 text-[11px] py-0.5">
          <span class="px-1.5 rounded text-[10px] font-mono flex-shrink-0" :style="{ background: d('rgba(239,68,68,0.1)', 'rgba(239,68,68,0.18)'), color: SEMANTIC.errors }">{{ e.response_code || '—' }}</span>
          <span class="flex-1 min-w-0 truncate" :style="{ color: d('rgba(0,0,0,0.7)', 'rgba(255,255,255,0.7)') }" :title="e.sample_message || e.sample_failure_message">{{ e.sample_message || e.sample_failure_message || e.label }}</span>
          <span class="tabular-nums flex-shrink-0" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">×{{ e.count }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
