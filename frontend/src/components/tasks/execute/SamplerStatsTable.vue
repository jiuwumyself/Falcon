<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronDown, ChevronRight, Table2 } from 'lucide-vue-next'
import type { ErrorAggregateRow, SamplerStat } from '@/types/task'
import { colorForHttpCode } from './dashboard/trends/semanticColors'
import { errorMessageOf } from './dashboard/trends/errorMeta'

const props = defineProps<{
  // 接口统计数据 + 错误聚合（由 SamplersTab 统一拉取后下传，含 'all' 行）
  stats: SamplerStat[]
  errorAggregates: ErrorAggregateRow[]
  // 终态时定格；运行中也展示当前累积值
  isTerminal: boolean
  isDark: boolean
}>()

const expandedLabel = ref<string | null>(null)

// 'all' 汇总行：后端预置(label==='all'),前端固定置顶,不参与排序
const ALL_LABEL = 'all'
function isAll(s: SamplerStat): boolean {
  return s.label === ALL_LABEL
}

// 错误聚合按接口分组，给展开行用（融合原「错误明细」tab 的 code+message+count）
const errorsByLabel = computed(() => {
  const m = new Map<string, ErrorAggregateRow[]>()
  for (const r of props.errorAggregates) {
    const arr = m.get(r.label)
    if (arr) arr.push(r)
    else m.set(r.label, [r])
  }
  return m
})

// body = 完整响应体（sample_response_body，errors.xml 抓的真实响应，≤500 字）；
// message 仅作 body 为空时的兜底（HTTP 派生短句）。
interface ErrLine { code: string; body: string; message: string; count: number }
function errorsFor(s: SamplerStat): ErrLine[] {
  const rows = isAll(s) ? [...props.errorAggregates] : (errorsByLabel.value.get(s.label) ?? [])
  if (rows.length) {
    return rows
      .sort((a, b) => b.count - a.count)
      .slice(0, isAll(s) ? 10 : 50)
      .map((r) => ({
        code: (r.response_code || '').trim() || '0',
        body: (r.sample_response_body || '').trim(),
        message: errorMessageOf(r),
        count: r.count,
      }))
  }
  // 兜底：无错误聚合（老 run / 还没拉）但 top_errors 有 → 只显示 code
  return (s.top_errors || []).map((e) => ({ code: e.reason, body: '', message: '', count: e.count }))
}

// SLA 阈值（暂用静态；v1.2 接 Service 模型后从那里取）
const P99_SLA_MS = 1000

// 点击表头排序：列 key + 取值。'success_rate' 派生,其余直接取字段。
type ColKey = 'label' | 'total' | 'success_rate' | 'avg_ms'
  | 'p50_ms' | 'p90_ms' | 'p99_ms' | 'max_ms' | 'avg_rps'
const COLUMNS: { key: ColKey; label: string; align: 'left' | 'right' }[] = [
  { key: 'label', label: '接口', align: 'left' },
  { key: 'total', label: '请求数', align: 'right' },
  { key: 'success_rate', label: '成功率', align: 'right' },
  { key: 'avg_ms', label: 'Avg', align: 'right' },
  { key: 'p50_ms', label: 'P50', align: 'right' },
  { key: 'p90_ms', label: 'P90', align: 'right' },
  { key: 'p99_ms', label: 'P99', align: 'right' },
  { key: 'max_ms', label: 'Max', align: 'right' },
  { key: 'avg_rps', label: 'RPS', align: 'right' },
]
const sortCol = ref<ColKey>('total')
const sortDir = ref<'asc' | 'desc'>('desc')

function setSort(key: ColKey) {
  if (sortCol.value === key) {
    sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'
  } else {
    sortCol.value = key
    sortDir.value = key === 'label' ? 'asc' : 'desc'  // 文本默认 A→Z,数值默认大→小
  }
}

function colValue(s: SamplerStat, key: ColKey): number | string {
  if (key === 'label') return s.label
  if (key === 'success_rate') return s.total ? s.success / s.total : 0
  return s[key]
}

const sortedStats = computed(() => {
  // 'all' 汇总行固定置顶,不参与排序；其余按当前列 + 方向排
  const all = props.stats.filter(isAll)
  const rest = props.stats.filter((s) => !isAll(s))
  const key = sortCol.value
  const sign = sortDir.value === 'desc' ? -1 : 1
  rest.sort((a, b) => {
    const va = colValue(a, key)
    const vb = colValue(b, key)
    const c = typeof va === 'string'
      ? String(va).localeCompare(String(vb))
      : (va as number) - (vb as number)
    return sign * c
  })
  return [...all, ...rest]
})

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

      <span
        v-if="stats.length"
        class="text-[10.5px]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.4)' }"
      >点击表头排序</span>
    </div>

    <!-- 空态 -->
    <div
      v-if="!stats.length"
      class="text-center py-6 text-[12px]"
      :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
    >运行结束后展示接口级统计</div>

    <!-- 表格 -->
    <div v-else class="overflow-x-auto">
      <table class="w-full text-[11.5px] tabular-nums">
        <thead>
          <tr :style="{ color: headerColor }">
            <th
              v-for="(col, ci) in COLUMNS"
              :key="col.key"
              class="font-medium pb-2 px-3 cursor-pointer select-none whitespace-nowrap"
              :class="[
                col.align === 'left' ? 'text-left' : 'text-right',
                ci === 0 ? 'pl-2' : '',
                ci === COLUMNS.length - 1 ? 'pr-2' : '',
              ]"
              :style="{ color: sortCol === col.key ? (isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.8)') : headerColor }"
              @click="setSort(col.key)"
            >
              <span class="inline-flex items-center gap-0.5" :class="col.align === 'right' ? 'flex-row-reverse' : ''">
                {{ col.label }}
                <ChevronDown
                  v-if="sortCol === col.key"
                  :size="11"
                  :style="{ transform: sortDir === 'asc' ? 'rotate(180deg)' : 'none' }"
                />
              </span>
            </th>
          </tr>
        </thead>
        <tbody>
          <template v-for="s in sortedStats" :key="s.label">
            <tr
              class="cursor-pointer transition-colors"
              :class="isAll(s) ? 'font-medium' : ''"
              :style="{
                color: cellColor,
                borderTop: `1px solid ${dividerColor}`,
                background: isAll(s) ? (isDark ? 'rgba(16,185,129,0.06)' : 'rgba(16,185,129,0.05)') : '',
              }"
              @click="toggleExpand(s.label)"
              @mouseenter="(e) => { if (!isAll(s)) (e.currentTarget as HTMLElement).style.background = rowHoverBg }"
              @mouseleave="(e) => { if (!isAll(s)) (e.currentTarget as HTMLElement).style.background = '' }"
            >
              <td class="py-2 pl-2 pr-3 max-w-[280px]">
                <div class="flex items-center gap-1.5">
                  <component
                    :is="expandedLabel === s.label ? ChevronDown : ChevronRight"
                    :size="11"
                    :color="isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)'"
                  />
                  <span class="truncate" :title="isAll(s) ? '全部接口汇总' : s.label">{{ isAll(s) ? '全部' : s.label }}</span>
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
                  v-if="errorsFor(s).length"
                  class="mt-3 text-[11px]"
                >
                  <div
                    class="font-medium mb-1"
                    :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }"
                  >错误明细</div>
                  <div class="flex flex-col gap-1.5">
                    <div
                      v-for="(err, i) in errorsFor(s)"
                      :key="i"
                      class="flex items-baseline gap-2 min-w-0"
                    >
                      <span
                        class="font-medium tabular-nums flex-shrink-0"
                        :style="{ color: colorForHttpCode(err.code) }"
                      >{{ err.code }}</span>
                      <!-- 完整响应 body 接在 code 后面（无 body 退回 HTTP 派生短句）-->
                      <span
                        class="font-mono text-[10.5px] break-all flex-1 min-w-0"
                        :style="{ color: isDark ? 'rgba(255,255,255,0.72)' : 'rgba(0,0,0,0.72)' }"
                      >{{ err.body || err.message }}</span>
                      <span class="flex-shrink-0 tabular-nums" :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">×{{ fmtInt(err.count) }}</span>
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
