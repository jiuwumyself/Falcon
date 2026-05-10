<script setup lang="ts">
import { computed } from 'vue'
import ErrorDetailList from '../ErrorDetailList.vue'
import type { TaskRun } from '@/types/task'

const props = defineProps<{
  run: TaskRun | null
  runId: string | null
  isDark: boolean
}>()

// § 12 S2：失败原因 5 类分桶 chips。终态时显示（error_breakdown 由 _on_finish 填）；
// 运行中 / 无错误时不渲染该 section。
const BUCKET_META: Record<string, { label: string; color: string; desc: string }> = {
  '4xx': { label: '4xx 业务异常', color: '#f59e0b', desc: '客户端业务校验失败（401/403/404/422 等）' },
  '5xx': { label: '5xx 服务端错误', color: '#ef4444', desc: '服务端崩溃 / 异常（500/502/503/504 等）' },
  assertion: { label: '断言失败', color: '#a855f7', desc: 'JMeter Assertion 失败（业务字段校验未通过）' },
  timeout: { label: '超时', color: '#06b6d4', desc: '读超时 / 连接超时（服务不响应或网络慢）' },
  connect_error: { label: '连接错误', color: '#3b82f6', desc: '连接被拒 / 域名解析失败 / 网络不可达' },
  other: { label: '其他', color: '#9ca3af', desc: '未匹配规则的错误（请检查 jmeter.log）' },
}

const buckets = computed(() => {
  const eb = props.run?.error_breakdown
  if (!eb) return []
  // 按数量降序，0 桶不显示
  return Object.entries(eb)
    .map(([key, count]) => ({
      key,
      count: Number(count) || 0,
      meta: BUCKET_META[key] ?? BUCKET_META.other,
    }))
    .filter((x) => x.count > 0)
    .sort((a, b) => b.count - a.count)
})

const totalErrors = computed(() =>
  buckets.value.reduce((sum, b) => sum + b.count, 0),
)
const totalRequests = computed(() => props.run?.total_requests ?? 0)

const showBreakdown = computed(() => buckets.value.length > 0)
</script>

<template>
  <div class="h-full flex flex-col overflow-hidden">
    <!-- § 12 S2 失败原因 5 类分桶（终态有数据时显示） -->
    <div
      v-if="showBreakdown"
      class="flex-shrink-0 p-3 border-b"
      :style="{
        borderColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
        background: isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)',
      }"
    >
      <div class="flex items-center mb-2">
        <span
          class="text-[12px] font-medium"
          :style="{ color: isDark ? 'rgba(255,255,255,0.75)' : 'rgba(0,0,0,0.7)' }"
        >失败原因分类</span>
        <span
          class="ml-2 text-[11px] tabular-nums"
          :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }"
        >
          总失败 {{ totalErrors.toLocaleString() }}
          <span v-if="totalRequests" class="opacity-70"> / {{ totalRequests.toLocaleString() }} 请求</span>
        </span>
      </div>
      <div class="flex flex-wrap gap-1.5">
        <span
          v-for="b in buckets"
          :key="b.key"
          class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px]"
          :title="b.meta.desc"
          :style="{
            background: `${b.meta.color}1a`,
            color: b.meta.color,
            border: `1px solid ${b.meta.color}33`,
          }"
        >
          <span>{{ b.meta.label }}</span>
          <span class="tabular-nums font-medium">{{ b.count.toLocaleString() }}</span>
          <span class="opacity-70 tabular-nums" v-if="totalErrors">
            ({{ ((b.count / totalErrors) * 100).toFixed(0) }}%)
          </span>
        </span>
      </div>
    </div>
    <!-- 原 ErrorDetailList：错误明细表 -->
    <div class="flex-1 min-h-0 overflow-y-auto">
      <ErrorDetailList :run-id="runId" :is-dark="isDark" />
    </div>
  </div>
</template>
