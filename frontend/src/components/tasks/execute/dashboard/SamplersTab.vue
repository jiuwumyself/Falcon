<script setup lang="ts">
import SamplerStatsTable from '../SamplerStatsTable.vue'

defineProps<{
  runId: string | null
  isTerminal: boolean
  isDark: boolean
}>()
</script>

<template>
  <div class="h-full overflow-y-auto">
    <SamplerStatsTable
      :run-id="runId"
      :is-terminal="isTerminal"
      :is-dark="isDark"
    />
  </div>
</template>
