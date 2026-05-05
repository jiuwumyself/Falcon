<script setup lang="ts">
import { CheckCircle2, XCircle } from 'lucide-vue-next'
import type { ValidateResult } from '@/types/task'

defineProps<{
  results: ValidateResult[]
  isDark: boolean
}>()

function statusColor(s: number): string {
  if (s >= 500) return '#ef4444'
  if (s >= 400) return '#f59e0b'
  if (s >= 200 && s < 300) return '#10b981'
  return '#6b7280'
}
</script>

<template>
  <div>
    <p
      class="text-[10px] uppercase tracking-[0.2em] mb-2"
      :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }"
    >校验结果 · {{ results.length }} 条</p>
    <div
      class="rounded-lg overflow-hidden"
      :style="{
        background: isDark ? 'rgba(255,255,255,0.015)' : 'rgba(0,0,0,0.015)',
        border: `1px solid ${isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.06)'}`,
      }"
    >
      <!-- Header -->
      <div
        class="grid text-[10px] uppercase tracking-wider px-3 py-2"
        :style="{
          gridTemplateColumns: '24px 1fr 1.4fr 50px 60px',
          gap: '8px',
          color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)',
          borderBottom: `1px solid ${isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'}`,
        }"
      >
        <span></span>
        <span>Sampler</span>
        <span>URL</span>
        <span>Status</span>
        <span>Time</span>
      </div>
      <!-- Rows -->
      <div
        v-for="(r, i) in results"
        :key="i"
        class="grid items-center px-3 py-2 text-[12px]"
        :style="{
          gridTemplateColumns: '24px 1fr 1.4fr 50px 60px',
          gap: '8px',
          borderTop: i > 0
            ? `1px solid ${isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)'}`
            : 'none',
        }"
      >
        <component
          :is="r.ok ? CheckCircle2 : XCircle"
          :size="14"
          :color="r.ok ? '#10b981' : '#ef4444'"
        />
        <span
          class="truncate"
          :style="{ color: isDark ? '#fff' : '#1a1a2e' }"
          :title="r.testname || '(未命名)'"
        >{{ r.testname || '(未命名)' }}</span>
        <span
          class="truncate font-mono text-[11px]"
          :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }"
          :title="r.url"
        >{{ r.url }}</span>
        <span
          class="font-mono text-[11px]"
          :style="{ color: statusColor(r.status) }"
        >{{ r.status || '-' }}</span>
        <span
          class="font-mono text-[11px]"
          :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }"
        >{{ r.elapsed_ms }}ms</span>

        <!-- Error row (spans all cols) -->
        <span
          v-if="!r.ok && r.error"
          class="col-span-5 text-[11px] text-red-500 mt-0.5"
        >⚠ {{ r.error }}</span>
        <span
          v-if="r.unresolved_vars && r.unresolved_vars.length"
          class="col-span-5 text-[11px] mt-0.5"
          style="color: #f59e0b"
        >⚠ 有未解析变量：{{ r.unresolved_vars.join(', ') }}（不在 CSV / 环境变量 / 提取器里）</span>
        <span
          v-for="(w, wi) in (r.warnings || [])"
          :key="`w-${wi}`"
          class="col-span-5 text-[11px] mt-0.5"
          style="color: #f97316"
        >⚠ {{ w }}</span>
      </div>

      <p
        v-if="!results.length"
        class="px-3 py-4 text-[11px] text-center"
        :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)' }"
      >(点上方的「校验」按钮触发 1 并发请求)</p>
    </div>
  </div>
</template>
