<script setup lang="ts">
import { Motion } from 'motion-v'

defineProps<{ isDark: boolean; rimColor: string; index: number }>()
</script>

<template>
  <Motion
    :initial="{ opacity: 0, y: 20 }"
    :animate="{ opacity: [0.3, 0.6, 0.3] }"
    :transition="{ duration: 2, repeat: Infinity, delay: index * 0.2 }"
    class="flex gap-3 pl-0"
  >
    <div class="flex-shrink-0 w-[44px] flex justify-center">
      <div
        class="w-[16px] h-[16px] rounded-full mt-2"
        :style="{ background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)' }"
      />
    </div>
    <div
      class="flex-1 rounded-xl p-3"
      :style="{
        background: isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)',
        backdropFilter: 'blur(40px)',
        border: `1px solid ${isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.03)'}`,
      }"
    >
      <div
        class="h-[10px] w-[60%] rounded mb-2"
        :style="{ background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)' }"
      />
      <div
        class="h-[12px] w-[85%] rounded mb-2"
        :style="{ background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)' }"
      />
      <div
        class="h-[8px] w-[40%] rounded"
        :style="{ background: isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)' }"
      />
    </div>
  </Motion>
</template>
