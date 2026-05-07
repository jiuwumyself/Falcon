<script setup lang="ts">
import ErrorDetailList from '../ErrorDetailList.vue'

defineProps<{
  runId: string | null
  isDark: boolean
}>()
</script>

<template>
  <div class="h-full overflow-y-auto">
    <ErrorDetailList :run-id="runId" :is-dark="isDark" />
  </div>
</template>
