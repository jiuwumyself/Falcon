<script setup lang="ts">
import { computed, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { bucketMeta } from './errorMeta'
import { tooltipBg } from './chartFactory'

use([PieChart, TooltipComponent, CanvasRenderer])

// 错误构成环形图：按失败原因 5 类分桶（4xx/5xx/assertion/timeout/connect_error/other）。
// 数据来自 TaskRun.error_breakdown（终态 _on_finish 填）。无错误时父层 v-if 不渲染。
// 设计：每片 80% alpha 实色 + 1.5px 实色描边；hover 取消描边、不透明度拉满；
// 中心数字 hover 时切到对应片（数 + 色 + 名），松手回总数；进场 600ms cubicOut。
const props = defineProps<{
  breakdown: Record<string, number>
  isDark: boolean
}>()

interface Slice { key: string; short: string; label: string; color: string; count: number; pct: number }

const total = computed(() =>
  Object.values(props.breakdown || {}).reduce((s, v) => s + (Number(v) || 0), 0),
)

const slices = computed<Slice[]>(() => {
  const t = total.value || 1
  return Object.entries(props.breakdown || {})
    .map(([key, count]) => {
      const m = bucketMeta(key)
      const c = Number(count) || 0
      return { key, short: m.short, label: m.label, color: m.color, count: c, pct: (c / t) * 100 }
    })
    .filter((s) => s.count > 0)
    .sort((a, b) => b.count - a.count)
})

// hover 中央数字 & 标签的状态（图上 hover 与图例 hover 共用同一 ref）
const hovered = ref<Slice | null>(null)
const centerCount = computed(() => (hovered.value?.count ?? total.value).toLocaleString())
const centerLabel = computed(() => hovered.value?.label ?? '总失败')
const centerColor = computed(() => hovered.value?.color ?? null)

const option = computed(() => ({
  // 进场 600ms + cubicOut：扫描旋转出来，比 echarts 默认 1s 紧凑利落
  animationDuration: 600,
  animationEasing: 'cubicOut' as const,
  // 鼠标移动到 / 离开 slice 的 emphasis 动画也短一点，避免 hover 抖动感
  animationDurationUpdate: 200,
  tooltip: {
    trigger: 'item' as const,
    formatter: (p: any) => `${p.name}<br/>${p.value.toLocaleString()}（${p.percent}%）`,
    ...tooltipBg(props.isDark),
    padding: 8,
    textStyle: { fontSize: 11 },
  },
  series: [{
    type: 'pie' as const,
    radius: ['64%', '96%'],
    center: ['50%', '50%'],
    avoidLabelOverlap: false,
    label: { show: false },
    labelLine: { show: false },
    // 默认态：80% alpha 填充（hex + 'cc'）+ 1.5px 实色描边
    data: slices.value.map((s) => ({
      name: s.label,
      value: s.count,
      itemStyle: {
        color: s.color + 'cc',
        borderColor: s.color,
        borderWidth: 1.5,
      },
    })),
    // hover：去描边 + 不透明度拉满（80%→100% 视觉加深），不放大避免抖
    emphasis: {
      scale: false,
      itemStyle: {
        opacity: 1,
        borderWidth: 0,
      },
    },
  }],
}))

function onHover(p: any) {
  const name = p?.data?.name ?? p?.name
  const s = slices.value.find((x) => x.label === name)
  if (s) hovered.value = s
}
function onLeave() {
  hovered.value = null
}
</script>

<template>
  <div class="flex flex-col h-full min-h-0">
    <div
      class="text-[12px] font-medium mb-2 flex-shrink-0 flex items-baseline gap-1.5"
      :style="{ color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.78)' }"
    >
      错误构成
      <span class="text-[11px] font-normal" :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">
        · 失败原因分类
      </span>
    </div>

    <div class="flex-1 min-h-0 flex flex-col items-center justify-center gap-3 overflow-hidden">
      <!-- 环形图 + 中心数字（hover 切换） -->
      <div class="relative flex-shrink-0" style="width: 140px; height: 140px">
        <VChart
          :option="option"
          autoresize
          @mouseover="onHover"
          @mouseout="onLeave"
        />
        <div class="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <span
            class="text-[20px] font-medium tabular-nums leading-none transition-colors duration-150"
            :style="{
              color: centerColor || (isDark ? 'rgba(255,255,255,0.9)' : 'rgba(0,0,0,0.82)'),
              letterSpacing: '-0.5px',
            }"
          >{{ centerCount }}</span>
          <span
            class="text-[10px] mt-1 transition-colors duration-150"
            :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
          >{{ centerLabel }}</span>
        </div>
      </div>

      <!-- 图例：行间细分隔线 + 数字 + 百分比；>50% 占比标红警示 -->
      <div class="w-full flex flex-col overflow-y-auto no-scrollbar">
        <div
          v-for="(s, i) in slices"
          :key="s.key"
          class="flex items-center justify-between py-1.5 text-[12px] cursor-default transition-colors"
          :style="{
            borderBottom: i < slices.length - 1
              ? `0.5px solid ${isDark ? 'rgba(255,255,255,0.07)' : 'rgba(0,0,0,0.06)'}`
              : 'none',
            background: hovered?.key === s.key
              ? (isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)')
              : 'transparent',
          }"
          :title="s.label"
          @mouseenter="hovered = s"
          @mouseleave="hovered = null"
        >
          <div class="flex items-center gap-2 min-w-0">
            <span class="w-2 h-2 rounded-full flex-shrink-0" :style="{ background: s.color }" />
            <span class="truncate" :style="{ color: isDark ? 'rgba(255,255,255,0.75)' : 'rgba(0,0,0,0.7)' }">{{ s.label }}</span>
          </div>
          <div class="flex items-center gap-3 flex-shrink-0">
            <span
              class="tabular-nums font-medium text-right"
              style="min-width: 38px"
              :style="{ color: isDark ? 'rgba(255,255,255,0.9)' : 'rgba(0,0,0,0.82)' }"
            >{{ s.count.toLocaleString() }}</span>
            <span
              class="tabular-nums text-[11px] text-right"
              style="min-width: 40px"
              :style="{ color: s.pct > 50 ? '#ef4444' : (isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)') }"
            >{{ s.pct.toFixed(1) }}%</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
