<script setup lang="ts">
import { Motion } from 'motion-v'
import { ArrowDown } from 'lucide-vue-next'
import FalconLogo from '@/components/FalconLogo.vue'

defineProps<{ isDark: boolean }>()
</script>

<template>
  <div class="h-screen flex-shrink-0 snap-start flex items-center justify-center relative">
    <div class="text-center px-5 max-w-[700px]">
      <Motion
        class="mb-8 flex justify-center"
        :initial="{ opacity: 0, scale: 0.6, rotate: -10 }"
        :animate="{ opacity: 1, scale: 1, rotate: 0 }"
        :transition="{ duration: 1, type: 'spring' }"
      >
        <FalconLogo :size="64" />
      </Motion>
      <Motion
        as="p"
        class="text-[11px] tracking-[0.3em] uppercase mb-4"
        :style="{ color: isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.25)' }"
        :initial="{ opacity: 0, y: 15 }"
        :animate="{ opacity: 1, y: 0 }"
        :transition="{ delay: 0.3 }"
      >
        Falcon Eyes · 全链路质量洞察中心
      </Motion>
      <Motion
        as="h1"
        class="text-[40px] lg:text-[56px] tracking-tight leading-tight"
        :style="{ color: isDark ? '#fff' : '#1a1a2e' }"
        :initial="{ opacity: 0, y: 40 }"
        :animate="{ opacity: 1, y: 0 }"
        :transition="{ delay: 0.4, type: 'spring', stiffness: 60 }"
      >
        每一次请求
        <br />
        <span
          style="
            background: linear-gradient(135deg, #3b82f6, #8b5cf6, #10b981);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
          "
        >都值得被守护</span>
      </Motion>
      <Motion
        as="p"
        class="text-[14px] mt-5 max-w-[420px] mx-auto"
        :style="{ color: isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.35)' }"
        :initial="{ opacity: 0 }"
        :animate="{ opacity: 1 }"
        :transition="{ delay: 0.7 }"
      >
        质量的尽头，是信任
      </Motion>
      <Motion
        class="mt-14 flex flex-col items-center gap-2"
        :animate="{ y: [0, 8, 0] }"
        :transition="{ duration: 2.5, repeat: Infinity }"
      >
        <span
          class="text-[10px] tracking-[0.2em]"
          :style="{ color: isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)' }"
        >SCROLL TO EXPLORE</span>
        <ArrowDown :size="14" :color="isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)'" />
      </Motion>
    </div>
  </div>
</template>
