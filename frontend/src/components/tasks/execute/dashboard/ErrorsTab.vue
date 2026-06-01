<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { runsApi } from '@/lib/api'
import type { ErrorAggregateRow, TaskRun } from '@/types/task'
import ErrorByEndpointTable from './trends/ErrorByEndpointTable.vue'

const props = defineProps<{
  run: TaskRun | null
  runId: string | null
  isDark: boolean
}>()

// 聚合表数据：v1.3 起 ErrorsTab 自己拉 + 自治轮询；TrendsLayout 不再管错误数据
const AGGREGATE_LIMIT = 100
const POLL_MS = 10_000
const TERMINAL_STATUSES = [
  'pre_check_failed', 'success', 'failed', 'timeout', 'cancelled',
] as const
const aggregates = ref<ErrorAggregateRow[]>([])
// loading 区分"还在拉" vs "真没数据"，否则切 tab 瞬间会假"暂无错误样本"误导用户
const loading = ref(false)
const fetchError = ref('')
let timer: number | null = null
let inflightToken = 0   // 竞态防御：runId 切换时旧请求晚到不能覆盖

async function fetchAggregates() {
  if (!props.runId) {
    aggregates.value = []
    loading.value = false
    return
  }
  const token = ++inflightToken
  // 首次 / runId 切换后第一次拉显式 loading；后续轮询保留旧数据不闪
  if (aggregates.value.length === 0) loading.value = true
  fetchError.value = ''
  try {
    const res = await runsApi.errorAggregates(props.runId, { limit: AGGREGATE_LIMIT })
    if (token !== inflightToken) return  // 已被新请求顶掉
    aggregates.value = res.aggregates
  } catch (e) {
    if (token !== inflightToken) return
    fetchError.value = String(e)
    // 失败保留旧数据，下一轮再试
  } finally {
    if (token === inflightToken) loading.value = false
  }
}

function startPoll() {
  stopPoll()
  void fetchAggregates()
  const status = props.run?.status
  // 终态 run 不需要继续轮询（聚合数据已经定型）
  if (status && (TERMINAL_STATUSES as readonly string[]).includes(status)) return
  timer = window.setInterval(fetchAggregates, POLL_MS)
}

function stopPoll() {
  if (timer != null) {
    clearInterval(timer)
    timer = null
  }
}

watch(
  () => [props.runId, props.run?.status] as const,
  () => {
    aggregates.value = []
    if (!props.runId) {
      stopPoll()
      loading.value = false
      return
    }
    startPoll()
  },
  { immediate: true },
)
onUnmounted(stopPoll)

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
    <!-- 聚合表：按 接口×code×msg 分组 + 行内下钻样本（含 body）-->
    <div class="flex-1 min-h-0 overflow-y-auto p-3">
      <!-- 首次加载：明确 loading 状态，避免假"暂无错误样本"-->
      <div
        v-if="loading && aggregates.length === 0"
        class="flex items-center justify-center gap-2 py-12 text-[12px]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
      >
        <div
          class="w-3 h-3 border-2 border-current border-r-transparent rounded-full animate-spin"
        />
        正在扫 JTL 提取错误聚合…大 run 可能需 3-5 秒
      </div>
      <div
        v-else-if="fetchError && aggregates.length === 0"
        class="text-center py-12 text-[12px]"
        :style="{ color: '#ef4444' }"
      >
        加载失败：{{ fetchError }}
      </div>
      <ErrorByEndpointTable
        v-else
        :rows="aggregates"
        :run-id="runId"
        :is-dark="isDark"
      />
    </div>
  </div>
</template>
