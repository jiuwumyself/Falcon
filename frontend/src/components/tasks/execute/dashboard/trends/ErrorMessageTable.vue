<script setup lang="ts">
import { computed } from 'vue'
import type { ErrorAggregateRow } from '@/types/task'
import { fmtInt } from './chartFactory'

// 服端聚合（aggregate=true）：每行 count 是真实总数，不受 limit 影响。
// sum 永远 = 真实总错误数，不会再出现"前端 sum 200 vs 实际 370"对账问题。
const props = defineProps<{
  rows: ErrorAggregateRow[]
  isDark: boolean
}>()

type MsgSource = 'message' | 'url' | 'label'

interface DisplayRow {
  responseCode: string
  responseMessage: string
  source: MsgSource    // message=正常 / url=URL 兜底 / label=接口名兜底
  count: number
}

// 优先级：sample_failure_message（断言/网络失败原因）→ sample_message（HTTP "Not Found" / setResponseMessage 注入的 body）
//        → sample_url（带具体路径，404 时最有用）→ label（最后兜底）
const displayRows = computed<DisplayRow[]>(() =>
  props.rows.map((r) => {
    const code = (r.response_code || '').trim() || '0'
    let msg = (r.sample_failure_message || r.sample_message || '').trim()
    let source: MsgSource = 'message'
    if (!msg) {
      const url = (r.sample_url || '').trim()
      if (url) {
        msg = url
        source = 'url'
      } else {
        msg = r.label || '(no message)'
        source = 'label'
      }
    }
    return { responseCode: code, responseMessage: msg, source, count: r.count }
  }),
)

const headerColor = computed(() =>
  props.isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.5)',
)
const cellColor = computed(() =>
  props.isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.85)',
)
const dividerColor = computed(() =>
  props.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
)

function codeColor(code: string): string {
  const n = parseInt(code, 10)
  if (Number.isNaN(n)) return '#a855f7' // 非数值（assertion / non-HTTP）
  if (n >= 500) return '#ef4444'
  if (n >= 400) return '#f59e0b'
  return '#3b82f6'
}
</script>

<template>
  <div class="flex flex-col h-full min-h-0">
    <div
      class="text-center text-[12px] mb-2 pb-2"
      :style="{
        color: isDark ? 'rgba(255,255,255,0.65)' : 'rgba(0,0,0,0.65)',
        borderBottom: `1px solid ${dividerColor}`,
      }"
    >
      错误信息
    </div>
    <div v-if="!displayRows.length" class="flex-1 flex items-center justify-center">
      <span
        class="text-[11.5px]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
      >
        ✓ 暂无错误样本
      </span>
    </div>
    <div v-else class="flex-1 min-h-0 overflow-y-auto">
      <table class="w-full text-[11.5px] tabular-nums">
        <thead class="sticky top-0" :style="{ background: isDark ? '#0f0f12' : '#f9f9fa' }">
          <tr :style="{ color: headerColor }">
            <th class="text-left font-medium pb-2 px-2 w-[80px]">code</th>
            <th class="text-left font-medium pb-2 px-2">message</th>
            <th class="text-right font-medium pb-2 px-2 w-[60px]">sum</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, i) in displayRows"
            :key="i"
            :style="{
              color: cellColor,
              borderTop: `1px solid ${dividerColor}`,
            }"
          >
            <td
              class="py-1.5 px-2 font-medium"
              :style="{ color: codeColor(row.responseCode) }"
            >
              {{ row.responseCode || '0' }}
            </td>
            <td class="py-1.5 px-2 max-w-[420px]">
              <!-- source=url：等宽字体显示完整 URL，错误最有用的兜底 -->
              <span
                v-if="row.source === 'url'"
                class="truncate block font-mono text-[11px]"
                :style="{ color: isDark ? 'rgba(255,255,255,0.78)' : 'rgba(0,0,0,0.75)' }"
                :title="`URL：${row.responseMessage}`"
              >{{ row.responseMessage }}</span>
              <!-- source=label：灰色斜体加尖括号，提示是按 sampler 名兜底 -->
              <span
                v-else-if="row.source === 'label'"
                class="truncate block italic"
                :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }"
                :title="`接口：${row.responseMessage}（旧 run 未开 saveservice.url；新 run 会显示具体 URL）`"
              >&lt;{{ row.responseMessage }}&gt;</span>
              <!-- source=message：正常 message -->
              <span
                v-else
                class="truncate block"
                :title="row.responseMessage"
              >{{ row.responseMessage }}</span>
            </td>
            <td class="py-1.5 px-2 text-right" :style="{ color: '#ef4444' }">
              {{ fmtInt(row.count) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
