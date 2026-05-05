<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { tasksApi, ApiError } from '@/lib/api'
import type { BizCategory, Task } from '@/types/task'
import TaskCreateWizard from '@/components/tasks/TaskCreateWizard.vue'

const router = useRouter()
const route = useRoute()
const initialTask = ref<Task | null>(null)
const loadError = ref('')

const defaultBiz = computed(() => (route.query.biz as BizCategory) || undefined)

function handleClose() {
  router.push('/performance')
}

onMounted(async () => {
  const idParam = route.query.id
  if (typeof idParam === 'string' && idParam) {
    const id = Number(idParam)
    if (!Number.isFinite(id)) return
    try {
      initialTask.value = await tasksApi.get(id)
    } catch (e) {
      loadError.value = e instanceof ApiError ? e.humanMessage : `加载任务失败：${e}`
    }
  }
})
</script>

<template>
  <div class="h-full overflow-visible pt-14 px-4 pb-4">
    <div class="w-full h-full px-2">
      <p v-if="loadError" class="text-[12px] text-red-500 px-3 py-2">{{ loadError }}</p>
      <TaskCreateWizard
        :initial-task="initialTask"
        :default-biz="defaultBiz"
        @close="handleClose"
      />
    </div>
  </div>
</template>
