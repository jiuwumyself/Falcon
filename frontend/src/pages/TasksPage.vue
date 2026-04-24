<script setup lang="ts">
import { useRouter } from 'vue-router'
import TaskCreateWizard from '@/components/tasks/TaskCreateWizard.vue'

const router = useRouter()

function handleClose() {
  router.push('/performance')
}
</script>

<template>
  <div class="h-full overflow-visible pt-14 px-4 pb-4">
    <div class="w-full h-full px-2">
      <TaskCreateWizard @close="handleClose" />
    </div>
  </div>
</template>
