<script setup lang="ts">
import { computed } from 'vue'
import { ExternalLink, AlertTriangle } from 'lucide-vue-next'
import type { PinpointTrace } from '@/types/task'

// § 11 Pinpoint v0：run 终态后慢 trace 元数据列表。
// 数据来自后端 /api/performance/runs/<run_id>/pinpoint-traces/，元数据级别（不含
// span tree），点击 "看 Pinpoint" 外链跳到原生界面看详情。
//
// 排序：按 service_name 分组 + 组内 elapsed desc（后端已 order_by）。

const props = defineProps<{
  traces: PinpointTrace[]
  isDark: boolean
}>()

// 按 service_name 分组（保持后端给的顺序，第一次出现即首位）
const grouped = computed(() => {
  const map = new Map<string, PinpointTrace[]>()
  for (const t of props.traces) {
    if (!map.has(t.service_name)) map.set(t.service_name, [])
    map.get(t.service_name)!.push(t)
  }
  return Array.from(map.entries())
})

function fmtElapsed(ms: number): string {
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(2)} s`
}

function fmtTime(ms: number): string {
  if (!ms) return '—'
  const d = new Date(ms)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}

function fmtTraceId(id: string): string {
  if (id.length <= 18) return id
  return `${id.slice(0, 8)}…${id.slice(-6)}`
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <div
      v-for="[svc, traces] in grouped"
      :key="svc"
      class="rounded-lg p-3"
      :style="{
        background: isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)',
        border: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
      }"
    >
      <div
        class="flex items-center justify-between mb-2 px-1"
        :style="{ color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.65)' }"
      >
        <span class="text-[12px] font-medium">{{ svc }}</span>
        <span class="text-[10.5px]" :style="{ opacity: 0.7 }">
          {{ traces.length }} 条慢 trace（按耗时降序）
        </span>
      </div>
      <table class="w-full text-[11px] tabular-nums">
        <thead>
          <tr :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">
            <th class="text-left font-normal pb-1.5 px-1">trace ID</th>
            <th class="text-right font-normal pb-1.5 px-1">耗时</th>
            <th class="text-right font-normal pb-1.5 px-1">起始时刻</th>
            <th class="text-left font-normal pb-1.5 px-1">异常</th>
            <th class="text-right font-normal pb-1.5 px-1"></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="t in traces"
            :key="t.id"
            class="border-t"
            :style="{
              borderColor: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)',
              color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.8)',
            }"
          >
            <td class="py-1 px-1 font-mono text-[10.5px]" :title="t.trace_id">{{ fmtTraceId(t.trace_id) }}</td>
            <td class="py-1 px-1 text-right" :style="{ color: t.elapsed_ms > 5000 ? '#ef4444' : t.elapsed_ms > 1000 ? '#f59e0b' : 'inherit' }">
              {{ fmtElapsed(t.elapsed_ms) }}
            </td>
            <td class="py-1 px-1 text-right" :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }">
              {{ fmtTime(t.start_ts_ms) }}
            </td>
            <td class="py-1 px-1">
              <span v-if="t.exception_type" class="inline-flex items-center gap-1 text-[10.5px]" :style="{ color: '#ef4444' }">
                <AlertTriangle :size="10" />
                {{ t.exception_type.split('.').pop() || t.exception_type }}
              </span>
              <span v-else :style="{ color: isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.3)' }">—</span>
            </td>
            <td class="py-1 px-1 text-right">
              <a
                v-if="t.pinpoint_detail_url"
                :href="t.pinpoint_detail_url"
                target="_blank"
                rel="noopener"
                class="inline-flex items-center gap-1 text-[10.5px] cursor-pointer"
                :style="{ color: '#3b82f6' }"
                :title="'在 Pinpoint 原生界面查看 span tree'"
              >
                看 Pinpoint
                <ExternalLink :size="10" />
              </a>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
