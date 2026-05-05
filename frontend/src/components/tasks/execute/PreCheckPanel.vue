<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  log: string
  isDark: boolean
}>()

const lines = computed(() => props.log.split('\n').filter(Boolean))

function lineColor(line: string): string {
  if (line.startsWith('✅')) return '#10b981'
  if (line.startsWith('❌')) return '#ef4444'
  if (line.startsWith('⚠️') || line.startsWith('⚠')) return '#f59e0b'
  return props.isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)'
}
</script>

<template>
  <div
    class="rounded-xl px-4 py-3 text-[12.5px] leading-[1.7] font-mono"
    :style="{
      background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
      border: isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.06)',
    }"
  >
    <div
      v-for="(line, i) in lines"
      :key="i"
      :style="{ color: lineColor(line) }"
    >{{ line }}</div>
    <div
      v-if="!lines.length"
      :style="{ color: isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.4)' }"
    >还没有预检输出</div>
  </div>
</template>
