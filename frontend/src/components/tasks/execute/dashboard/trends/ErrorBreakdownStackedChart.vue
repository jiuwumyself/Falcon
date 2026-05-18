<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, TitleComponent, LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { api } from '@/lib/api'
import HoverTip from './HoverTip.vue'

use([LineChart, GridComponent, TooltipComponent, TitleComponent, LegendComponent, CanvasRenderer])

// stress 场景末位卡：5 桶错误类型堆叠时序（4xx / 5xx / timeout / connect_error /
// assertion / other）。诊断"错误是哪种"——一眼区分"业务挂 / 应用挂 / LB 拒接 / 慢爆"。
//
// 数据来源：扫 jtl 端点 `/runs/:run_id/error-breakdown-timeseries/`，运行中也有
// 数据（不依赖 _on_finish 才填的 TaskRun.error_breakdown 总数）。
const props = defineProps<{
  runId: string | null
  isTerminal: boolean
  xRange?: [number, number] | null
  isDark: boolean
}>()

type Bucket = '4xx' | '5xx' | 'timeout' | 'connect_error' | 'assertion' | 'other'
const BUCKETS: Bucket[] = ['4xx', '5xx', 'timeout', 'connect_error', 'assertion', 'other']
const BUCKET_LABEL: Record<Bucket, string> = {
  '4xx': '4xx',
  '5xx': '5xx',
  timeout: 'Timeout',
  connect_error: '连接错',
  assertion: '断言',
  other: '其他',
}
// 颜色 = ErrorsTab 的同款（用户已熟悉）
const BUCKET_COLOR: Record<Bucket, string> = {
  '4xx': '#60a5fa',
  '5xx': '#f97316',
  timeout: '#a855f7',
  connect_error: '#ef4444',
  assertion: '#eab308',
  other: '#94a3b8',
}

const data = ref<Record<Bucket, [number, number][]>>({
  '4xx': [], '5xx': [], timeout: [], connect_error: [], assertion: [], other: [],
})
let pollTimer: ReturnType<typeof setInterval> | null = null

async function fetchOnce(): Promise<void> {
  if (!props.runId) return
  try {
    const res = await api<Record<Bucket, [number, number][]>>(
      `/runs/${props.runId}/error-breakdown-timeseries/`,
    )
    data.value = res
  } catch {
    // 静默：jtl 不存在 / run 未启动时正常
  }
}

function startPolling(): void {
  if (pollTimer) return
  fetchOnce()
  pollTimer = setInterval(fetchOnce, 5000)
}
function stopPolling(): void {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

watch(
  () => [props.runId, props.isTerminal] as const,
  ([runId, terminal]) => {
    stopPolling()
    if (!runId) return
    if (terminal) fetchOnce()
    else startPolling()
  },
  { immediate: true },
)
onUnmounted(stopPolling)
onMounted(() => { if (props.runId) (props.isTerminal ? fetchOnce() : startPolling()) })

const totals = computed(() => {
  const out: Record<Bucket, number> = {
    '4xx': 0, '5xx': 0, timeout: 0, connect_error: 0, assertion: 0, other: 0,
  }
  for (const b of BUCKETS) for (const [, v] of data.value[b]) out[b] += v
  return out
})
const totalAll = computed(() => BUCKETS.reduce((s, b) => s + totals.value[b], 0))

const hasData = computed(() => totalAll.value > 0)

// 上面那行 chip 同时承担 legend 切换：点 chip 隐藏 / 显示对应桶曲线
// 内置 echarts legend 已删，避免重复
const visibleBuckets = ref<Record<Bucket, boolean>>({
  '4xx': true, '5xx': true, timeout: true, connect_error: true, assertion: true, other: true,
})
function toggleBucket(b: Bucket) {
  visibleBuckets.value[b] = !visibleBuckets.value[b]
}

const option = computed(() => {
  const axisColor = props.isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)'
  const gridLine = props.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'
  const xMin = props.xRange?.[0]
  const xMax = props.xRange?.[1]
  return {
    grid: { left: 50, right: 18, top: 28, bottom: 30 },
    tooltip: {
      trigger: 'axis' as const,
      backgroundColor: props.isDark ? 'rgba(20,20,22,0.92)' : 'rgba(255,255,255,0.95)',
      borderColor: props.isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)',
      textStyle: { color: props.isDark ? '#fff' : '#000', fontSize: 11 },
    },
    xAxis: {
      type: 'time' as const,
      ...(xMin && xMax ? { min: xMin, max: xMax } : {}),
      axisLine: { lineStyle: { color: axisColor } },
      axisLabel: { color: axisColor, fontSize: 10 },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value' as const,
      name: '错误数/s',
      nameLocation: 'middle' as const,
      nameGap: 38,
      nameTextStyle: { color: axisColor, fontSize: 10 },
      axisLine: { lineStyle: { color: axisColor } },
      axisLabel: { color: axisColor, fontSize: 10 },
      splitLine: { lineStyle: { color: gridLine } },
    },
    // 隐藏的桶传空数组：堆叠图直接收缩；保留 BUCKET 数量稳定（避免 echarts 重建图）
    series: BUCKETS.map((b) => ({
      name: BUCKET_LABEL[b],
      type: 'line' as const,
      stack: 'err',
      smooth: false,
      symbol: 'none',
      lineStyle: { width: 0.6, color: BUCKET_COLOR[b] },
      areaStyle: { color: BUCKET_COLOR[b], opacity: 0.85 },
      data: visibleBuckets.value[b] ? data.value[b] : [],
    })),
  }
})
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="flex items-center justify-between gap-2 px-1 mb-1">
      <HoverTip
        :tip="'核心问题（压力）：找崩溃点 + 错误类型转移诊断（4xx → 5xx → connect refused 三段递进）\n\n判读条件：\n· 全段平稳 4xx → 业务参数错，跟压力无关，先修脚本\n· 4xx → 5xx 爆增 → 应用层挂了（OOM / panic / 死锁）\n· 5xx → connect_error 转移 → 实例已被 LB 摘掉，整片挂\n· 单 timeout 飙升 → 数据库 / 下游慢，没真正挂\n· assertion 高 → 业务结果不符（不是性能错，是结果错）'"
        :is-dark="isDark"
      >
        <span class="text-[11.5px]"
              :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }">
          错误类型堆叠（按秒）
        </span>
      </HoverTip>
      <div
        class="text-[10.5px] tabular-nums flex items-center gap-2 flex-nowrap justify-end overflow-x-auto no-scrollbar"
        :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
      >
        <span
          v-for="b in BUCKETS"
          :key="b"
          class="cursor-pointer select-none flex-shrink-0"
          :style="{
            color: BUCKET_COLOR[b],
            opacity: visibleBuckets[b] ? 1 : 0.35,
          }"
          :title="visibleBuckets[b] ? '点击隐藏该桶曲线' : '点击显示该桶曲线'"
          @click="toggleBucket(b)"
        >{{ BUCKET_LABEL[b] }} {{ totals[b] }}</span>
      </div>
    </div>
    <div class="flex-1 min-h-0">
      <VChart
        v-if="hasData"
        :option="option"
        autoresize
        style="width: 100%; height: 100%"
      />
      <div
        v-else
        class="h-full flex items-center justify-center text-[11px]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)' }"
      >
        {{ runId ? '尚未出现错误样本' : '未启动 run' }}
      </div>
    </div>
  </div>
</template>
