<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { runsApi } from '@/lib/api'
import type { ErrorAggregateRow, SamplerStat, TaskRun } from '@/types/task'
import SamplerStatsTable from '../SamplerStatsTable.vue'
import ErrorDonutChart from './trends/ErrorDonutChart.vue'
import SamplerRtRangeChart from './trends/SamplerRtRangeChart.vue'

// 合并后的「接口统计」容器（原「错误明细」tab 已并入此处）：
// 统一拉 sampler-stats + error-aggregates，喂给 → RT 横条图 + 接口表（展开行错误明细）；
// donut 错误构成走 run.error_breakdown。一次拉取，避免子组件重复请求。
const props = defineProps<{
  run: TaskRun | null
  runId: string | null
  isTerminal: boolean
  isDark: boolean
}>()

const stats = ref<SamplerStat[]>([])
const errorAggregates = ref<ErrorAggregateRow[]>([])
const loading = ref(false)
const errorMessage = ref('')
let inflightToken = 0   // 竞态防御：切 run 时旧请求晚到不能覆盖

async function load() {
  if (!props.runId) {
    stats.value = []
    errorAggregates.value = []
    return
  }
  const token = ++inflightToken
  loading.value = true
  errorMessage.value = ''
  try {
    const [s, agg] = await Promise.all([
      runsApi.samplerStats(props.runId),
      runsApi.errorAggregates(props.runId, { limit: 100 }).catch(() => ({ aggregates: [] })),
    ])
    if (token !== inflightToken) return
    stats.value = s
    errorAggregates.value = agg.aggregates
  } catch (e) {
    if (token !== inflightToken) return
    errorMessage.value = e instanceof Error ? e.message : String(e)
    stats.value = []
    errorAggregates.value = []
  } finally {
    if (token === inflightToken) loading.value = false
  }
}

onMounted(load)
watch(() => props.runId, load)

// donut：整体错误桶；任一桶 > 0 才显示
const breakdown = computed(() => props.run?.error_breakdown ?? {})
const hasErrors = computed(() =>
  Object.values(breakdown.value).some((v) => (Number(v) || 0) > 0),
)

const cardStyle = computed(() => ({
  background: props.isDark ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.6)',
  border: props.isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.06)',
  backdropFilter: 'blur(40px)',
}))
</script>

<template>
  <div class="h-full overflow-y-auto p-3 flex flex-col gap-3">
    <!-- 加载 / 错误态 -->
    <div
      v-if="loading && !stats.length"
      class="text-center py-6 text-[12px]"
      :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }"
    >加载中…</div>
    <div
      v-else-if="errorMessage && !stats.length"
      class="text-center py-6 text-[12px]"
      :style="{ color: '#ef4444' }"
    >加载失败：{{ errorMessage }}</div>

    <template v-else>
      <!-- 顶部图表行：错误构成 donut（有错才显示）+ 各接口响应时间分布横条。
           不写死高度：横条图按接口数自撑高，donut 卡片 items-stretch 跟齐。 -->
      <div v-if="stats.length" class="flex gap-3 items-stretch flex-shrink-0">
        <div
          v-if="hasErrors"
          class="rounded-2xl p-4 flex-shrink-0 w-[300px]"
          :style="cardStyle"
        >
          <ErrorDonutChart :breakdown="breakdown" :is-dark="isDark" />
        </div>
        <div class="rounded-2xl p-4 flex-1 min-w-0" :style="cardStyle">
          <SamplerRtRangeChart :stats="stats" :is-dark="isDark" />
        </div>
      </div>

      <!-- 接口级统计表（'all' 置顶 + 点表头排序 + 展开行错误明细）-->
      <SamplerStatsTable
        :stats="stats"
        :error-aggregates="errorAggregates"
        :is-terminal="isTerminal"
        :is-dark="isDark"
      />
    </template>
  </div>
</template>
