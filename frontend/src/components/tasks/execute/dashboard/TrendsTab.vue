<script setup lang="ts">
import TrendsLayout from './trends/TrendsLayout.vue'
import type { RunMetrics, Task, TaskRun } from '@/types/task'

defineProps<{
  task: Task
  run: TaskRun | null
  runs: TaskRun[]
  metrics: RunMetrics | null
  isDark: boolean
}>()
</script>

<template>
  <TrendsLayout :task="task" :run="run" :runs="runs" :metrics="metrics" :is-dark="isDark" />
</template>
