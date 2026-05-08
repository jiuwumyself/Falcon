<script setup lang="ts">
import TrendsLayout from './trends/TrendsLayout.vue'
import type { RunMetrics, TaskRun } from '@/types/task'

defineProps<{
  run: TaskRun | null
  metrics: RunMetrics | null
  isDark: boolean
}>()
</script>

<template>
  <TrendsLayout :run="run" :metrics="metrics" :is-dark="isDark" />
</template>
