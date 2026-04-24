<script setup lang="ts">
import { computed } from 'vue'
import { Globe } from 'lucide-vue-next'
import { useTheme } from '@/composables/useTheme'
import GlassNav from '@/components/GlassNav.vue'

const { theme } = useTheme()
const isDark = computed(() => theme.value === 'dark')
</script>

<template>
  <div class="h-full overflow-y-auto pt-24 px-5 pb-16">
    <div class="max-w-[1100px] mx-auto">
      <div class="mb-8 mt-2">
        <h1
          class="text-[28px] tracking-tight"
          :style="{ color: isDark ? '#fff' : '#1a1a2e' }"
        >接口板块</h1>
        <p
          class="text-[13px] mt-1"
          :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.4)' }"
        >Automated API testing &amp; monitoring</p>
      </div>
      <GlassNav class="p-10 flex flex-col items-center justify-center min-h-[400px]">
        <div
          class="w-16 h-16 rounded-3xl flex items-center justify-center mb-4"
          style="background: rgba(16,185,129,0.1)"
        >
          <Globe :size="28" color="#10b981" />
        </div>
        <p class="text-[15px]" :style="{ color: isDark ? '#fff' : '#1a1a2e' }">API Testing Suite</p>
        <p
          class="text-[12px] mt-2 text-center max-w-[300px]"
          :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.4)' }"
        >Build, run and monitor automated API test scenarios.</p>
      </GlassNav>
    </div>
  </div>
</template>
