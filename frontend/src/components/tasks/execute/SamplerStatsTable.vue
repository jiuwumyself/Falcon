<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ChevronDown, ChevronRight, Table2 } from 'lucide-vue-next'
import { runsApi } from '@/lib/api'
import type { SamplerSortKey, SamplerStat } from '@/types/task'

const props = defineProps<{
  runId: string | null
  // 终态时定格；运行中也展示当前累积值（mock 模式下静态展示）
  isTerminal: boolean
  isDark: boolean
}>()

const stats = ref<SamplerStat[]>([])
const loading = ref(false)
const errorMessage = ref('')
const sortKey = ref<SamplerSortKey>('error_rate_desc')
const expandedLabel = ref<string | null>(null)

// SLA 阈值（暂用静态；v1.2 接 Service 模型后从那里取）
const P99_SLA_MS = 1000

const SORT_OPTIONS: { value: SamplerSortKey; label: string }[] = [
  { value: 'error_rate_desc', label: '错误率降序' },
  { value: 'total_desc', label: '请求数降序' },
  { value: 'p99_desc', label: 'P99 降序' },
]

async function load() {
  if (!props.runId) {
    stats.value = []
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    stats.value = await runsApi.samplerStats(props.runId)
  } catch (e) {
    errorMessage.value = String(e)
    stats.value = []
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.runId, load)

const sortedStats = computed(() => {
  const arr = [...stats.value]
  switch (sortKey.value) {
    case 'error_rate_desc':
      return arr.sort(
        (a, b) => errorRate(b) - errorRate(a) || b.total - a.total,
      )
    case 'total_desc':
      return arr.sort((a, b) => b.total - a.total)
    case 'p99_desc':
      return arr.sort((a, b) => b.p99_ms - a.p99_ms)
  }
})

function errorRate(s: SamplerStat): number {
  if (!s.total) return 0
  return (s.error / s.total) * 100
}

function successRateColor(pct: number): string {
  if (pct < 99) return '#ef4444'
  if (pct < 99.5) return '#f59e0b'
  return '#10b981'
}

function p99Color(ms: number): string {
  if (ms > P99_SLA_MS) return '#ef4444'
  return ''
}

function fmtInt(n: number): string {
  return Math.round(n).toLocaleString()
}

function fmtKB(bytes: number): string {
  if (bytes < 1024) return `${Math.round(bytes)} B`
  return `${(bytes / 1024).toFixed(1)} KB`
}

function fmtPct(n: number): string {
  return n.toFixed(n >= 99.95 ? 2 : 1)
}

function toggleExpand(label: string) {
  expandedLabel.value = expandedLabel.value === label ? null : label
}

const cardStyle = computed(() => ({
  background: props.isDark ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.6)',
  border: props.isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.06)',
  backdropFilter: 'blur(40px)',
}))

const headerColor = computed(() =>
  props.isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.5)',
)
const cellColor = computed(() =>
  props.isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.85)',
)
const dividerColor = computed(() =>
  props.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
)
const rowHoverBg = computed(() =>
  props.isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)',
)
</script>

<template>
  <div class="rounded-2xl p-4" :style="cardStyle">
    <!-- 头部 -->
    <div class="flex items-center justify-between mb-3">
      <div class="flex items-center gap-2">
        <Table2 :size="14" :color="headerColor" />
        <span
          class="text-[12.5px] font-medium"
          :style="{ color: isDark ? 'rgba(255,255,255,0.75)' : 'rgba(0,0,0,0.75)' }"
        >接口级统计</span>
        <span
          v-if="!isTerminal && stats.length"
          class="text-[10.5px] px-1.5 py-0.5 rounded"
          :style="{
            background: 'rgba(59,130,246,0.12)',
            color: '#3b82f6',
          }"
        >运行中累计</span>
      </div>

      <select
        v-if="stats.length"
        v-model="sortKey"
        class="text-[11.5px] px-2 py-1 rounded-md cursor-pointer outline-none"
        :style="{
          background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
          border: isDark ? '1px solid rgba(255,255,255,0.08)' : '1px solid rgba(0,0,0,0.08)',
          color: isDark ? 'rgba(255,255,255,0.8)' : 'rgba(0,0,0,0.75)',
        }"
      >
        <option
          v-for="opt in SORT_OPTIONS"
          :key="opt.value"
          :value="opt.value"
        >{{ opt.label }}</option>
      </select>
    </div>

    <!-- 空 / 加载 / 错误态 -->
    <div
      v-if="loading"
      class="text-center py-6 text-[12px]"
      :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }"
    >加载中…</div>
    <div
      v-else-if="errorMessage"
      class="text-center py-6 text-[12px]"
      :style="{ color: '#ef4444' }"
    >加载失败：{{ errorMessage }}</div>
    <div
      v-else-if="!stats.length"
      class="text-center py-6 text-[12px]"
      :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
    >运行结束后展示接口级统计</div>

    <!-- 表格 -->
    <div v-else class="overflow-x-auto">
      <table class="w-full text-[11.5px] tabular-nums">
        <thead>
          <tr :style="{ color: headerColor }">
            <th class="text-left font-medium pb-2 pl-2 pr-3">接口</th>
            <th class="text-right font-medium pb-2 px-3">请求数</th>
            <th class="text-right font-medium pb-2 px-3">成功率</th>
            <th class="text-right font-medium pb-2 px-3">Avg</th>
            <th class="text-right font-medium pb-2 px-3">P50</th>
            <th class="text-right font-medium pb-2 px-3">P90</th>
            <th class="text-right font-medium pb-2 px-3">P99</th>
            <th class="text-right font-medium pb-2 px-3">Max</th>
            <th class="text-right font-medium pb-2 px-3 pr-2">RPS</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="s in sortedStats" :key="s.label">
            <tr
              class="cursor-pointer transition-colors"
              :style="{
                color: cellColor,
                borderTop: `1px solid ${dividerColor}`,
              }"
              @click="toggleExpand(s.label)"
              @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.background = rowHoverBg)"
              @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.background = '')"
            >
              <td class="py-2 pl-2 pr-3 max-w-[280px]">
                <div class="flex items-center gap-1.5">
                  <component
                    :is="expandedLabel === s.label ? ChevronDown : ChevronRight"
                    :size="11"
                    :color="isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)'"
                  />
                  <span class="truncate" :title="s.label">{{ s.label }}</span>
                </div>
              </td>
              <td class="py-2 px-3 text-right">{{ fmtInt(s.total) }}</td>
              <td
                class="py-2 px-3 text-right font-medium"
                :style="{ color: successRateColor(((s.success / s.total) || 0) * 100) }"
              >
                {{ fmtPct(((s.success / s.total) || 0) * 100) }}%
              </td>
              <td class="py-2 px-3 text-right">{{ fmtInt(s.avg_ms) }}</td>
              <td class="py-2 px-3 text-right">{{ fmtInt(s.p50_ms) }}</td>
              <td class="py-2 px-3 text-right">{{ fmtInt(s.p90_ms) }}</td>
              <td
                class="py-2 px-3 text-right font-medium"
                :style="p99Color(s.p99_ms) ? { color: p99Color(s.p99_ms) } : {}"
              >
                {{ fmtInt(s.p99_ms) }}
              </td>
              <td class="py-2 px-3 text-right">{{ fmtInt(s.max_ms) }}</td>
              <td class="py-2 px-3 pr-2 text-right">{{ s.avg_rps.toFixed(1) }}</td>
            </tr>

            <!-- 展开详情 -->
            <tr v-if="expandedLabel === s.label" :style="{ borderTop: `1px solid ${dividerColor}` }">
              <td colspan="9" class="py-3 px-4">
                <div
                  class="flex flex-wrap gap-x-6 gap-y-2 text-[11px]"
                  :style="{ color: isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.6)' }"
                >
                  <div>Min <span :style="{ color: cellColor }">{{ fmtInt(s.min_ms) }} ms</span></div>
                  <div>平均响应大小 <span :style="{ color: cellColor }">{{ fmtKB(s.avg_bytes) }}</span></div>
                  <div>失败数 <span :style="{ color: '#ef4444' }">{{ fmtInt(s.error) }}</span> / <span :style="{ color: cellColor }">{{ fmtInt(s.total) }}</span></div>
                </div>
                <div
                  v-if="s.top_errors.length"
                  class="mt-3 text-[11px]"
                >
                  <div
                    class="font-medium mb-1"
                    :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }"
                  >Top 错误</div>
                  <div class="flex flex-col gap-1">
                    <div
                      v-for="(err, i) in s.top_errors"
                      :key="i"
                      class="flex items-center gap-2"
                    >
                      <span
                        class="inline-block w-1.5 h-1.5 rounded-full"
                        :style="{ background: '#ef4444' }"
                      />
                      <span :style="{ color: cellColor }" class="truncate">{{ err.reason }}</span>
                      <span :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">×{{ err.count }}</span>
                    </div>
                  </div>
                </div>
                <div
                  v-else
                  class="mt-2 text-[11px]"
                  :style="{ color: '#10b981' }"
                >✓ 全部请求成功</div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>
