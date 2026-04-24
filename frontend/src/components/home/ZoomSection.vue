<script setup lang="ts">
import { computed, ref, type Ref } from 'vue'
import { Motion, useInView, useScroll, useTransform } from 'motion-v'
import { TrendingUp, Activity } from 'lucide-vue-next'
import AnimNum from './AnimNum.vue'
import Spark from './Spark.vue'
import { useTheme } from '@/composables/useTheme'

interface ModData {
  taskVolume: number
  dispatchCount: number
  successRate: number
  meanConcurrency: number
  successTrend: number[]
  concurrencyTrend: number[]
}
export interface ModuleDef {
  id: string
  title: string
  subtitle: string
  icon: any
  color: string
  colorEnd: string
  data: ModData
  desc: string
  index: string
}

const props = defineProps<{
  mod: ModuleDef
  scrollContainer: Ref<HTMLElement | null>
}>()

const { theme } = useTheme()
const isDark = computed(() => theme.value === 'dark')
const sectionRef = ref<HTMLDivElement | null>(null)
const inView = useInView(sectionRef, { amount: 0.35 })

const { scrollYProgress } = useScroll({
  target: sectionRef,
  container: props.scrollContainer,
  offset: ['start end', 'end start'],
})

const scale = useTransform(scrollYProgress, [0, 0.4, 0.6, 1], [0.5, 1, 1, 1.5])
const opacity = useTransform(scrollYProgress, [0, 0.3, 0.7, 1], [0, 1, 1, 0])
const blur = useTransform(scrollYProgress, [0, 0.35, 0.65, 1], [30, 0, 0, 20])
const blurStr = useTransform(blur, (v) => `blur(${v}px)`)
const rotateX = useTransform(scrollYProgress, [0, 0.4, 0.6, 1], [15, 0, 0, -10])

const ringOpacities = [0.3, 0.5, 0.7].map((d) =>
  useTransform(scrollYProgress, [d - 0.15, d, d + 0.15], [0, 0.15, 0]),
)

const METRICS = [
  { key: 'taskVolume', label: '任务总量', en: 'Tasks', decimals: 0 },
  { key: 'dispatchCount', label: '调度频次', en: 'Dispatch', decimals: 0 },
  { key: 'successRate', label: '达标率', en: 'Success', decimals: 1, suffix: '%' },
  { key: 'meanConcurrency', label: '均值负载', en: 'Concurrency', decimals: 0 },
] as const
</script>

<template>
  <div
    ref="sectionRef"
    class="h-screen flex-shrink-0 snap-start relative overflow-hidden"
    style="perspective: 1200px"
  >
    <Motion
      v-for="(i, idx) in [0, 1, 2]"
      :key="idx"
      class="absolute inset-0 flex items-center justify-center pointer-events-none"
      :style="{ opacity: ringOpacities[idx] }"
    >
      <div
        class="rounded-full border"
        :style="{
          width: `${300 + i * 200}px`,
          height: `${300 + i * 200}px`,
          borderColor: `${mod.color}15`,
        }"
      />
    </Motion>

    <Motion
      class="h-full flex items-center justify-center px-8 lg:px-16"
      :style="{ scale, opacity, filter: blurStr, rotateX, transformOrigin: 'center center' }"
    >
      <div class="w-full max-w-[1000px] text-center">
        <Motion
          class="mb-10"
          :initial="{ opacity: 0, scale: 0.3 }"
          :animate="inView ? { opacity: 1, scale: 1 } : {}"
          :transition="{ type: 'spring', stiffness: 150, damping: 15 }"
        >
          <div
            class="inline-flex items-center justify-center w-20 h-20 rounded-3xl mb-5 relative"
            :style="{ background: `${mod.color}10` }"
          >
            <component :is="mod.icon" :size="32" :color="mod.color" />
            <Motion
              class="absolute inset-0 rounded-3xl"
              :animate="
                inView
                  ? { boxShadow: [`0 0 0px ${mod.color}00`, `0 0 50px ${mod.color}20`, `0 0 0px ${mod.color}00`] }
                  : {}
              "
              :transition="{ duration: 3, repeat: Infinity }"
            />
          </div>
          <div class="flex items-center justify-center gap-3 mb-3">
            <div class="h-[1px] w-8" :style="{ background: `${mod.color}30` }" />
            <span
              class="text-[11px] tracking-[0.3em] uppercase"
              :style="{ color: `${mod.color}80` }"
            >{{ mod.index }}</span>
            <div class="h-[1px] w-8" :style="{ background: `${mod.color}30` }" />
          </div>
          <h2
            class="text-[40px] lg:text-[56px] tracking-tight"
            :style="{ color: isDark ? '#fff' : '#1a1a2e' }"
          >{{ mod.title }}</h2>
          <p
            class="text-[13px] mt-2"
            :style="{ color: isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.35)' }"
          >{{ mod.subtitle }}</p>
        </Motion>

        <div class="flex justify-center gap-6 lg:gap-12 mb-10 flex-wrap">
          <Motion
            v-for="(m, mi) in METRICS"
            :key="m.key"
            :initial="{ opacity: 0, scale: 0.5 }"
            :animate="inView ? { opacity: 1, scale: 1 } : {}"
            :transition="{ delay: 0.15 + mi * 0.08, type: 'spring', stiffness: 200 }"
            class="min-w-[120px] rounded-2xl p-4 lg:p-5"
            :style="{
              background: isDark ? 'rgba(255,255,255,0.025)' : 'rgba(0,0,0,0.02)',
              border: `1px solid ${isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)'}`,
            }"
          >
            <p
              class="text-[30px] lg:text-[36px] tracking-tighter leading-none"
              :style="{ color: isDark ? '#fff' : '#1a1a2e' }"
            >
              <AnimNum
                :value="(mod.data as any)[m.key]"
                :decimals="m.decimals"
                :suffix="'suffix' in m ? m.suffix : ''"
                :trigger="inView"
              />
            </p>
            <p
              class="text-[9px] mt-2 uppercase tracking-wider"
              :style="{ color: isDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.3)' }"
            >{{ m.label }}</p>
          </Motion>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-8 max-w-[700px] mx-auto">
          <Motion
            :initial="{ opacity: 0, y: 30 }"
            :animate="inView ? { opacity: 1, y: 0 } : {}"
            :transition="{ delay: 0.5 }"
          >
            <p
              class="text-[10px] mb-3 flex items-center justify-center gap-1.5 uppercase tracking-wider"
              :style="{ color: isDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.3)' }"
            >
              <TrendingUp :size="10" /> 成功率
            </p>
            <Spark :data="mod.data.successTrend" :color="mod.color" :uid="`s-${mod.id}`" />
          </Motion>
          <Motion
            :initial="{ opacity: 0, y: 30 }"
            :animate="inView ? { opacity: 1, y: 0 } : {}"
            :transition="{ delay: 0.6 }"
          >
            <p
              class="text-[10px] mb-3 flex items-center justify-center gap-1.5 uppercase tracking-wider"
              :style="{ color: isDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.3)' }"
            >
              <Activity :size="10" /> 并发
            </p>
            <Spark
              :data="mod.data.concurrencyTrend"
              :color="mod.colorEnd"
              :threshold="-1"
              :uid="`c-${mod.id}`"
            />
          </Motion>
        </div>
      </div>
    </Motion>
  </div>
</template>
