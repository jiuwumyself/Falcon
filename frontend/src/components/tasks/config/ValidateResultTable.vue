<script setup lang="ts">
import { ref, computed } from 'vue'
import { Motion, AnimatePresence } from 'motion-v'
import { CheckCircle2, XCircle, AlertTriangle, ChevronRight, Layers } from 'lucide-vue-next'
import type { ValidateResult, ExecutedTg } from '@/types/task'

const props = withDefaults(
  defineProps<{
    results: ValidateResult[]
    isDark: boolean
    warnings?: string[]
    executedTgs?: ExecutedTg[]
  }>(),
  { warnings: () => [], executedTgs: () => [] },
)

function statusColor(s: number): string {
  if (s >= 500) return '#ef4444'
  if (s >= 400) return '#f59e0b'
  if (s >= 200 && s < 300) return '#10b981'
  return '#6b7280'
}

const expanded = ref<Set<number>>(new Set())

function toggle(i: number) {
  const s = new Set(expanded.value)
  if (s.has(i)) s.delete(i)
  else s.add(i)
  expanded.value = s
}

function hasDetail(r: ValidateResult): boolean {
  return Boolean(
    r.response_body || r.response_headers || r.request_data ||
    (r.assertion_failures && r.assertion_failures.length),
  )
}

const summary = computed(() => {
  const ok = props.results.filter((r) => r.ok).length
  return { ok, fail: props.results.length - ok }
})
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-2">
      <p
        class="text-[10px] uppercase tracking-[0.2em]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }"
      >试跑结果 · {{ results.length }} 条</p>
      <p
        v-if="results.length"
        class="text-[11px]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }"
      >
        <span style="color: #10b981">{{ summary.ok }} 成功</span>
        <span class="mx-1.5">·</span>
        <span style="color: #ef4444">{{ summary.fail }} 失败</span>
      </p>
    </div>

    <!-- 本次执行的 TG 列表（让用户对齐：禁用 TG 不参与） -->
    <div
      v-if="executedTgs.length"
      class="flex items-start gap-2 px-3 py-2 mb-1.5 rounded-md text-[11px]"
      :style="{
        background: isDark ? 'rgba(139,92,246,0.08)' : 'rgba(139,92,246,0.06)',
        border: `1px solid ${isDark ? 'rgba(139,92,246,0.25)' : 'rgba(139,92,246,0.22)'}`,
        color: isDark ? 'rgba(167,139,250,0.95)' : '#7c3aed',
      }"
    >
      <Layers :size="12" class="flex-shrink-0 mt-0.5" />
      <div class="flex-1 min-w-0">
        本次执行
        <span v-for="(tg, i) in executedTgs" :key="tg.path">
          <span class="font-medium">{{ tg.testname || tg.path }}</span>
          <span
            class="text-[10px] ml-0.5"
            :style="{ color: isDark ? 'rgba(167,139,250,0.55)' : 'rgba(124,58,237,0.55)' }"
          >({{ tg.kind.replace('ThreadGroup', 'TG') }})</span>
          <span v-if="i < executedTgs.length - 1">、</span>
        </span>
        ；其它 TG 已禁用，不参与
      </div>
    </div>

    <!-- 任务级 warnings 横条（DNS 注入跳过等提示） -->
    <div
      v-for="(w, i) in warnings"
      :key="`top-w-${i}`"
      class="flex items-start gap-2 px-3 py-2 mb-1.5 rounded-md text-[11px]"
      :style="{
        background: isDark ? 'rgba(245,158,11,0.08)' : 'rgba(245,158,11,0.08)',
        border: `1px solid ${isDark ? 'rgba(245,158,11,0.25)' : 'rgba(245,158,11,0.22)'}`,
        color: '#b45309',
      }"
    >
      <AlertTriangle :size="12" class="flex-shrink-0 mt-0.5" />
      <span>{{ w }}</span>
    </div>
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
          gridTemplateColumns: '20px 24px 1fr 1.4fr 50px 60px',
          gap: '8px',
          color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)',
          borderBottom: `1px solid ${isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'}`,
        }"
      >
        <span></span>
        <span></span>
        <span>Sampler</span>
        <span>URL</span>
        <span>Status</span>
        <span>Time</span>
      </div>

      <!-- Rows -->
      <template v-for="(r, i) in results" :key="i">
        <div
          class="grid items-center px-3 py-2 text-[12px] cursor-pointer"
          :style="{
            gridTemplateColumns: '20px 24px 1fr 1.4fr 50px 60px',
            gap: '8px',
            borderTop: i > 0
              ? `1px solid ${isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)'}`
              : 'none',
            background: expanded.has(i)
              ? (isDark ? 'rgba(255,255,255,0.025)' : 'rgba(0,0,0,0.02)')
              : 'transparent',
          }"
          @click="toggle(i)"
        >
          <Motion
            as="div"
            :animate="{ rotate: expanded.has(i) ? 90 : 0 }"
            :transition="{ duration: 0.18 }"
            class="flex"
          >
            <ChevronRight
              :size="12"
              :color="hasDetail(r)
                ? (isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.5)')
                : (isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.18)')"
            />
          </Motion>
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
            class="col-span-6 text-[11px] text-red-500 mt-0.5"
          >⚠ {{ r.error }}</span>
          <span
            v-if="r.unresolved_vars && r.unresolved_vars.length"
            class="col-span-6 text-[11px] mt-0.5"
            style="color: #f59e0b"
          >⚠ 有未解析变量：{{ r.unresolved_vars.join(', ') }}（不在 CSV / 环境变量 / 提取器里）</span>
          <span
            v-for="(w, wi) in (r.warnings || [])"
            :key="`w-${wi}`"
            class="col-span-6 text-[11px] mt-0.5"
            style="color: #f97316"
          >⚠ {{ w }}</span>
        </div>

        <!-- Expanded details panel -->
        <AnimatePresence>
          <Motion
            v-if="expanded.has(i)"
            :key="`detail-${i}`"
            :initial="{ opacity: 0, height: 0 }"
            :animate="{ opacity: 1, height: 'auto' }"
            :exit="{ opacity: 0, height: 0 }"
            :transition="{ duration: 0.2 }"
            class="overflow-hidden"
            :style="{
              background: isDark ? 'rgba(0,0,0,0.18)' : 'rgba(0,0,0,0.025)',
              borderTop: `1px solid ${isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)'}`,
            }"
          >
            <div class="px-4 py-3 flex flex-col gap-3 text-[11px]">
              <!-- 断言失败列表 -->
              <div
                v-if="r.assertion_failures && r.assertion_failures.length"
                class="flex flex-col gap-1"
              >
                <p
                  class="text-[10px] uppercase tracking-wider"
                  style="color: #ef4444"
                >断言失败 · {{ r.assertion_failures.length }} 条</p>
                <div
                  v-for="(af, afi) in r.assertion_failures"
                  :key="afi"
                  class="px-2 py-1 rounded font-mono text-[11px]"
                  :style="{
                    background: isDark ? 'rgba(239,68,68,0.08)' : 'rgba(239,68,68,0.06)',
                    color: '#ef4444',
                  }"
                >{{ af }}</div>
              </div>

              <!-- response_message（HTTP status 行的 message） -->
              <div v-if="r.response_message" class="flex gap-2">
                <span
                  class="text-[10px] uppercase tracking-wider w-[90px] flex-shrink-0"
                  :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }"
                >Response Msg</span>
                <span
                  class="font-mono"
                  :style="{ color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.65)' }"
                >{{ r.response_message }}</span>
              </div>

              <!-- 请求详情 -->
              <div v-if="r.request_data" class="flex flex-col gap-1">
                <p
                  class="text-[10px] uppercase tracking-wider"
                  :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }"
                >Request</p>
                <pre
                  class="font-mono text-[11px] whitespace-pre-wrap break-all px-2 py-1.5 rounded max-h-[200px] overflow-auto"
                  :style="{
                    background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)',
                    color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)',
                  }"
                >{{ r.request_data }}</pre>
              </div>

              <!-- 响应头 -->
              <div v-if="r.response_headers" class="flex flex-col gap-1">
                <p
                  class="text-[10px] uppercase tracking-wider"
                  :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }"
                >Response Headers</p>
                <pre
                  class="font-mono text-[11px] whitespace-pre-wrap break-all px-2 py-1.5 rounded max-h-[200px] overflow-auto"
                  :style="{
                    background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)',
                    color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)',
                  }"
                >{{ r.response_headers }}</pre>
              </div>

              <!-- 响应体 -->
              <div v-if="r.response_body" class="flex flex-col gap-1">
                <p
                  class="text-[10px] uppercase tracking-wider"
                  :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }"
                >Response Body</p>
                <pre
                  class="font-mono text-[11px] whitespace-pre-wrap break-all px-2 py-1.5 rounded max-h-[400px] overflow-auto"
                  :style="{
                    background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)',
                    color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)',
                  }"
                >{{ r.response_body }}</pre>
              </div>

              <p
                v-if="!hasDetail(r)"
                class="text-[11px]"
                :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
              >(此条没捕获到响应详情，可能 sampler 没真跑或被前置失败短路)</p>
            </div>
          </Motion>
        </AnimatePresence>
      </template>

      <p
        v-if="!results.length"
        class="px-3 py-4 text-[11px] text-center"
        :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)' }"
      >(点上方的「试跑」按钮，每个接口跑 1 次)</p>
    </div>
  </div>
</template>
