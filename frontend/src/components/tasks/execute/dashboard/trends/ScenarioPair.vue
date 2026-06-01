<script setup lang="ts">
import type { ScenarioMockSpec } from './trendsMockData'
// 图①（复用现有场景图）
import ConcurrencyRpsChart from './ConcurrencyRpsChart.vue'
import SoakLatencyTrendChart from './SoakLatencyTrendChart.vue'
import VuRpsDualAxisChart from './VuRpsDualAxisChart.vue'
import TargetRpsVsActualChart from './TargetRpsVsActualChart.vue'
// 图②（新建）
import BaselineVersionBar from './BaselineVersionBar.vue'
import RtScatterChart from './RtScatterChart.vue'
import ErrorBreakdownStackedChart from './ErrorBreakdownStackedChart.vue'
import MemoryLeakChart from './MemoryLeakChart.vue'
import QueueDepthChart from './QueueDepthChart.vue'
import ThroughputLatencyBubbleChart from './ThroughputLatencyBubbleChart.vue'

// 一个场景的「图① + 图②」并排卡。mock 预览 + 真实模式共用。
// 图① 按场景分发到既有组件；图② 按场景分发到新建组件。
// 数据分流：spec 里带 mock 数据则用 mock；否则真实模式靠 runId 自取 / 走空态占位。
defineProps<{
  spec: ScenarioMockSpec
  xRange: [number, number] | null
  isDark: boolean
  // 画廊里加段标题；选中单场景时父级已有上下文，可隐藏
  showHeader?: boolean
  // 真实模式：stress 错误堆叠按 runId 自取（mock 模式传 spec.errorBuckets，不用 runId）
  runId?: string | null
  isTerminal?: boolean
}>()

const usesConcurrency = (id: string) => ['baseline', 'load', 'stress'].includes(id)
</script>

<template>
  <div class="flex flex-col">
    <div
      v-if="showHeader !== false"
      class="flex items-center gap-1.5 mb-1.5 px-0.5"
    >
      <span class="w-2 h-2 rounded-full flex-shrink-0" :style="{ background: spec.color }" />
      <span
        class="text-[12px] font-medium"
        :style="{ color: isDark ? 'rgba(255,255,255,0.8)' : 'rgba(0,0,0,0.72)' }"
      >{{ spec.label }}</span>
      <span class="text-[10px]" :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.4)' }">
        · {{ spec.id }}
      </span>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
      <!-- 图① -->
      <div class="h-[210px] rounded-lg p-2"
           :style="{ background: isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.015)' }">
        <ConcurrencyRpsChart
          v-if="usesConcurrency(spec.id)"
          :rps="spec.rps" :vu="spec.vu" :is-dark="isDark"
        />
        <SoakLatencyTrendChart
          v-else-if="spec.id === 'soak'"
          :lat="spec.lat" :x-range="xRange" :is-dark="isDark"
        />
        <VuRpsDualAxisChart
          v-else-if="spec.id === 'spike'"
          :rps="spec.rps" :vu="spec.vu" :x-range="xRange" :is-dark="isDark"
        />
        <TargetRpsVsActualChart
          v-else-if="spec.id === 'throughput'"
          :rps="spec.rps" :target-rps-per-sec="spec.targetRpsPerSec" :x-range="xRange" :is-dark="isDark"
        />
      </div>

      <!-- 图②（按场景恒渲染；真实模式缺数据走组件空态 / baseline 占位）-->
      <div class="h-[210px] rounded-lg p-2"
           :style="{ background: isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.015)' }">
        <template v-if="spec.id === 'baseline'">
          <BaselineVersionBar
            v-if="spec.baselineVersions"
            :current="spec.baselineVersions.current"
            :baseline="spec.baselineVersions.baseline"
            :self-is-baseline="spec.baselineVersions.selfIsBaseline"
            :is-dark="isDark"
          />
          <div
            v-else
            class="h-full flex items-center justify-center text-center text-[11px] px-3"
            :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.4)' }"
          >本次运行尚无接口统计（终态后显示）</div>
        </template>
        <RtScatterChart
          v-else-if="spec.id === 'load'"
          :points="spec.rtScatter || []" :is-dark="isDark"
        />
        <ErrorBreakdownStackedChart
          v-else-if="spec.id === 'stress'"
          :mock-buckets="spec.errorBuckets ?? null"
          :run-id="spec.errorBuckets ? null : (runId ?? null)"
          :is-terminal="isTerminal ?? true"
          :x-range="xRange" :is-dark="isDark"
        />
        <MemoryLeakChart
          v-else-if="spec.id === 'soak'"
          :heap="spec.memoryLeak?.heap ?? []" :handles="spec.memoryLeak?.handles ?? []"
          :x-range="xRange" :is-dark="isDark"
        />
        <QueueDepthChart
          v-else-if="spec.id === 'spike'"
          :depth="spec.queueDepth ?? []" :x-range="xRange" :is-dark="isDark"
        />
        <ThroughputLatencyBubbleChart
          v-else-if="spec.id === 'throughput'"
          :stats="spec.samplerStats ?? []" :is-dark="isDark"
        />
      </div>
    </div>
  </div>
</template>
