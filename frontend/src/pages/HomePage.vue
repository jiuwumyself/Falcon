<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMotionValueEvent, useScroll } from 'motion-v'
import { Zap, Globe, Eye } from 'lucide-vue-next'
import { useTheme } from '@/composables/useTheme'
import HeroSection from '@/components/home/HeroSection.vue'
import ZoomSection, { type ModuleDef } from '@/components/home/ZoomSection.vue'
import ScrollDots from '@/components/home/ScrollDots.vue'

const PERF_DATA = {
  taskVolume: 12847,
  dispatchCount: 3216,
  successRate: 97.3,
  meanConcurrency: 842,
  successTrend: [96.1, 97.8, 95.2, 98.4, 94.7, 97.1, 96.5, 98.9, 97.3, 97.3],
  concurrencyTrend: [720, 810, 650, 890, 760, 830, 920, 780, 860, 842],
}
const UI_DATA = {
  taskVolume: 5234,
  dispatchCount: 1489,
  successRate: 93.8,
  meanConcurrency: 128,
  successTrend: [91.2, 94.5, 92.8, 95.1, 90.3, 93.7, 94.2, 92.1, 93.8, 93.8],
  concurrencyTrend: [110, 135, 98, 142, 120, 130, 115, 145, 125, 128],
}
const API_DATA = {
  taskVolume: 28493,
  dispatchCount: 7832,
  successRate: 99.1,
  meanConcurrency: 2140,
  successTrend: [98.7, 99.2, 98.9, 99.5, 99.1, 98.8, 99.3, 99.0, 99.4, 99.1],
  concurrencyTrend: [1980, 2050, 2200, 1890, 2100, 2300, 2050, 2180, 2090, 2140],
}

const MODULES: ModuleDef[] = [
  {
    id: 'performance', title: '性能板块', subtitle: 'Load Dynamics',
    icon: Zap, color: '#3b82f6', colorEnd: '#60a5fa',
    data: PERF_DATA, desc: '全链路压测的实时律动', index: '01',
  },
  {
    id: 'ui', title: 'UI 板块', subtitle: 'Visual Integrity',
    icon: Eye, color: '#8b5cf6', colorEnd: '#a78bfa',
    data: UI_DATA, desc: '极致对称的组件设计', index: '02',
  },
  {
    id: 'api', title: '接口板块', subtitle: 'Connectivity Sync',
    icon: Globe, color: '#10b981', colorEnd: '#34d399',
    data: API_DATA, desc: '最纯粹的测试底色', index: '03',
  },
]
const DOT_COLORS = ['rgba(255,255,255,0.4)', '#3b82f6', '#8b5cf6', '#10b981']

const { theme } = useTheme()
const isDark = computed(() => theme.value === 'dark')

const scrollRef = ref<HTMLDivElement | null>(null)
const activeSection = ref(0)

const { scrollYProgress } = useScroll({ container: scrollRef })
useMotionValueEvent(scrollYProgress, 'change', (v: number) => {
  activeSection.value = Math.min(Math.round(v * 3), 3)
})
</script>

<template>
  <div class="h-full relative" :style="{ color: isDark ? '#fff' : '#1a1a2e' }">
    <ScrollDots :active="activeSection" :total="4" :colors="DOT_COLORS" />
    <div
      ref="scrollRef"
      class="h-full overflow-y-auto relative"
      style="scroll-snap-type: y mandatory; scroll-behavior: smooth"
    >
      <HeroSection :is-dark="isDark" />
      <ZoomSection
        v-for="mod in MODULES"
        :key="mod.id"
        :mod="mod"
        :scroll-container="(scrollRef as any)"
      />
    </div>
  </div>
</template>
