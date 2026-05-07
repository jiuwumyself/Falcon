<script setup lang="ts">
import RunMetricsCharts from '../RunMetricsCharts.vue'
import type { RunMetrics } from '@/types/task'

defineProps<{
  metrics: RunMetrics | null
  isDark: boolean
}>()
</script>

<template>
  <div class="h-full overflow-y-auto">
    <RunMetricsCharts :metrics="metrics" :is-dark="isDark" />
  </div>
</template>
