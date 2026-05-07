<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { AlertTriangle, ChevronDown, ChevronRight, CheckCircle2 } from 'lucide-vue-next'
import { runsApi } from '@/lib/api'
import type { ErrorCodeBucket, ErrorSample } from '@/types/task'

const props = defineProps<{
  runId: string | null
  isDark: boolean
}>()

const samples = ref<ErrorSample[]>([])
const total = ref(0)
const loading = ref(false)
const errorMessage = ref('')

const samplerFilter = ref<string>('all')
const codeBucket = ref<ErrorCodeBucket>('all')
const limit = ref(50)
const expandedKey = ref<string | null>(null)

const BUCKET_OPTIONS: { value: ErrorCodeBucket; label: string }[] = [
  { value: 'all', label: '全部错误' },
  { value: '4xx', label: '4xx' },
  { value: '5xx', label: '5xx' },
  { value: 'assertion', label: '断言失败' },
  { value: 'timeout', label: '超时 / 网络异常' },
]

async function load() {
  if (!props.runId) {
    samples.value = []
    total.value = 0
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    const res = await runsApi.errorSamples(props.runId, {
      limit: limit.value,
      sampler: samplerFilter.value === 'all' ? undefined : samplerFilter.value,
      codeBucket: codeBucket.value,
    })
    samples.value = res.samples
    total.value = res.total
  } catch (e) {
    errorMessage.value = String(e)
    samples.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.runId, () => {
  expandedKey.value = null
  load()
})
watch([samplerFilter, codeBucket, limit], load)

// 接口下拉选项 = 已加载样本里的 sampler 名集合
const samplerOptions = computed<string[]>(() => {
  const set = new Set<string>()
  for (const s of samples.value) set.add(s.label)
  return Array.from(set).sort()
})

function bucketTagColor(e: ErrorSample): { bg: string; fg: string; label: string } {
  if (e.response_code.startsWith('Non HTTP')) {
    return { bg: 'rgba(148,163,184,0.18)', fg: '#94a3b8', label: 'Timeout' }
  }
  if (e.failure_message.startsWith('Assertion')) {
    return { bg: 'rgba(168,85,247,0.18)', fg: '#a855f7', label: 'Assert' }
  }
  if (/^5\d{2}$/.test(e.response_code)) {
    return { bg: 'rgba(239,68,68,0.18)', fg: '#ef4444', label: e.response_code }
  }
  if (/^4\d{2}$/.test(e.response_code)) {
    return { bg: 'rgba(245,158,11,0.18)', fg: '#f59e0b', label: e.response_code }
  }
  return { bg: 'rgba(148,163,184,0.18)', fg: '#94a3b8', label: e.response_code.slice(0, 16) }
}

function fmtTime(ts: number): string {
  return new Date(ts).toLocaleTimeString('zh-CN', { hour12: false })
}

function singleLineReason(e: ErrorSample): string {
  if (e.failure_message) return e.failure_message
  if (e.response_message) return e.response_message
  return e.response_code
}

function rowKey(e: ErrorSample, idx: number): string {
  return `${e.timestamp}-${idx}`
}

function toggle(key: string) {
  expandedKey.value = expandedKey.value === key ? null : key
}

const cardStyle = computed(() => ({
  background: props.isDark ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.6)',
  border: props.isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.06)',
  backdropFilter: 'blur(40px)',
}))
const cellColor = computed(() =>
  props.isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.85)',
)
const subColor = computed(() =>
  props.isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)',
)
const dividerColor = computed(() =>
  props.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
)
const selectStyle = computed(() => ({
  background: props.isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
  border: props.isDark ? '1px solid rgba(255,255,255,0.08)' : '1px solid rgba(0,0,0,0.08)',
  color: props.isDark ? 'rgba(255,255,255,0.8)' : 'rgba(0,0,0,0.75)',
}))
const bodyBlockStyle = computed(() => ({
  background: props.isDark ? 'rgba(0,0,0,0.4)' : 'rgba(0,0,0,0.04)',
  color: props.isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.85)',
  border: props.isDark ? '1px solid rgba(255,255,255,0.05)' : '1px solid rgba(0,0,0,0.05)',
}))
</script>

<template>
  <div class="rounded-2xl p-4" :style="cardStyle">
    <!-- 头部 -->
    <div class="flex flex-wrap items-center justify-between gap-2 mb-3">
      <div class="flex items-center gap-2">
        <AlertTriangle :size="14" color="#ef4444" />
        <span
          class="text-[12.5px] font-medium"
          :style="{ color: isDark ? 'rgba(255,255,255,0.75)' : 'rgba(0,0,0,0.75)' }"
        >错误请求</span>
        <span
          v-if="total"
          class="text-[10.5px] px-1.5 py-0.5 rounded"
          :style="{
            background: 'rgba(239,68,68,0.12)',
            color: '#ef4444',
          }"
        >共 {{ total }} 条</span>
      </div>

      <div v-if="samples.length || samplerFilter !== 'all' || codeBucket !== 'all'" class="flex items-center gap-2">
        <select
          v-model="samplerFilter"
          class="text-[11.5px] px-2 py-1 rounded-md cursor-pointer outline-none max-w-[200px]"
          :style="selectStyle"
        >
          <option value="all">全部接口</option>
          <option
            v-for="opt in samplerOptions"
            :key="opt"
            :value="opt"
          >{{ opt }}</option>
        </select>
        <select
          v-model="codeBucket"
          class="text-[11.5px] px-2 py-1 rounded-md cursor-pointer outline-none"
          :style="selectStyle"
        >
          <option
            v-for="opt in BUCKET_OPTIONS"
            :key="opt.value"
            :value="opt.value"
          >{{ opt.label }}</option>
        </select>
      </div>
    </div>

    <!-- 加载 / 错误态 -->
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

    <!-- 全成功 -->
    <div
      v-else-if="!samples.length && samplerFilter === 'all' && codeBucket === 'all'"
      class="flex items-center justify-center gap-2 py-6 rounded-xl"
      :style="{
        background: isDark ? 'rgba(16,185,129,0.08)' : 'rgba(16,185,129,0.06)',
        color: '#10b981',
      }"
    >
      <CheckCircle2 :size="14" />
      <span class="text-[12px]">全部请求成功</span>
    </div>

    <!-- 筛选后无结果 -->
    <div
      v-else-if="!samples.length"
      class="text-center py-6 text-[12px]"
      :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
    >无匹配错误</div>

    <!-- 列表 -->
    <div v-else class="flex flex-col">
      <div
        v-for="(e, i) in samples"
        :key="rowKey(e, i)"
        class="cursor-pointer py-2.5 px-2 rounded-md transition-colors"
        :style="{
          borderTop: i === 0 ? 'none' : `1px solid ${dividerColor}`,
        }"
        @click="toggle(rowKey(e, i))"
        @mouseenter="(ev) => ((ev.currentTarget as HTMLElement).style.background = isDark ? 'rgba(255,255,255,0.025)' : 'rgba(0,0,0,0.02)')"
        @mouseleave="(ev) => ((ev.currentTarget as HTMLElement).style.background = '')"
      >
        <div class="flex items-center gap-2.5 text-[12px]" :style="{ color: cellColor }">
          <component
            :is="expandedKey === rowKey(e, i) ? ChevronDown : ChevronRight"
            :size="11"
            :color="isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)'"
            class="shrink-0"
          />
          <span class="tabular-nums shrink-0" :style="{ color: subColor }">{{ fmtTime(e.timestamp) }}</span>
          <span
            class="text-[10px] font-medium px-1.5 py-0.5 rounded shrink-0"
            :style="{
              background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)',
              color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.6)',
            }"
          >{{ e.method }}</span>
          <span class="truncate flex-1" :title="e.label">{{ e.label }}</span>
          <span
            class="text-[10.5px] font-medium px-1.5 py-0.5 rounded shrink-0"
            :style="{
              background: bucketTagColor(e).bg,
              color: bucketTagColor(e).fg,
            }"
          >{{ bucketTagColor(e).label }}</span>
          <span class="text-[11px] tabular-nums shrink-0" :style="{ color: subColor }">
            {{ e.elapsed_ms }}ms
          </span>
        </div>
        <div
          class="mt-1 ml-[24px] text-[11px] truncate"
          :style="{ color: subColor }"
          :title="singleLineReason(e)"
        >{{ singleLineReason(e) }}</div>

        <!-- 展开 response body -->
        <div v-if="expandedKey === rowKey(e, i)" class="mt-2 ml-[24px]">
          <div
            class="text-[10.5px] uppercase tracking-wider mb-1"
            :style="{ color: subColor }"
          >Response body（已截断 ≤ 1 KB）</div>
          <pre
            class="text-[11px] p-3 rounded-lg overflow-x-auto whitespace-pre-wrap break-all max-h-[240px] overflow-y-auto"
            :style="bodyBlockStyle"
          >{{ e.response_body || '(空响应体)' }}</pre>
        </div>
      </div>

      <!-- 加载更多 -->
      <div
        v-if="total > samples.length"
        class="mt-3 text-center"
      >
        <button
          class="text-[11.5px] px-3 py-1.5 rounded-md cursor-pointer transition-colors"
          :style="{
            background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
            color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.65)',
            border: `1px solid ${dividerColor}`,
          }"
          @click="limit += 50"
        >加载更多（已显示 {{ samples.length }} / {{ total }}）</button>
      </div>
      <div
        v-else-if="samples.length"
        class="mt-3 text-center text-[11px]"
        :style="{ color: subColor }"
      >已显示全部 {{ samples.length }} 条</div>
    </div>

    <!-- 空状态（runId 为 null） -->
    <div
      v-if="!runId && !loading"
      class="text-center py-2 text-[11px]"
      :style="{ color: subColor }"
    ></div>
  </div>
</template>
