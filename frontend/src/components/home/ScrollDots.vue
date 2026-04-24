<script setup lang="ts">
import { Motion } from 'motion-v'
import { useTheme } from '@/composables/useTheme'
import { computed } from 'vue'

const props = defineProps<{
  active: number
  total: number
  colors: string[]
}>()

const { theme } = useTheme()
const isDark = computed(() => theme.value === 'dark')

const items = computed(() => Array.from({ length: props.total }))
</script>

<template>
  <div class="fixed right-5 top-1/2 -translate-y-1/2 z-40 flex flex-col gap-3">
    <Motion
      v-for="(_, i) in items"
      :key="i"
      class="w-2 rounded-full"
      :animate="{
        height: active === i ? 28 : 8,
        background: active === i
          ? colors[i]
          : isDark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.12)',
        boxShadow: active === i ? `0 0 10px ${colors[i]}40` : 'none',
      }"
      :transition="{ type: 'spring', stiffness: 300, damping: 25 }"
    />
  </div>
</template>
