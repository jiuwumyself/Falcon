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
// URL ?step=<id> → wizard 启动时定位到该步；刷新 / 重打开保持
const initialStep = computed(() =>
  typeof route.query.step === 'string' ? route.query.step : null,
)

function handleClose() {
  router.push('/performance')
}

// wizard 切 step → 把 ?step=<id> 写回 URL（replace 不留 history 栈，避免回退按钮一直在 wizard 内）
function onStepChange(stepId: string) {
  if (route.query.step === stepId) return
  router.replace({ query: { ...route.query, step: stepId } })
}

// wizard 新建上传成功 → 把 task.id 写回 URL。
// 必须做这步：MainLayout 的 <RouterView :key="r.fullPath"> 让 ?step= 一变 TasksPage 就
// 整体重建，重建后 onMounted 看 ?id 才能重拉 task 填回 initialTask；否则切 step 后
// wizard 的 uploadedTask 会丢，回到 Step 1 又显示空 dropzone。
function onCreated(task: Task) {
  initialTask.value = task
  if (route.query.id === String(task.id)) return
  router.replace({ query: { ...route.query, id: String(task.id) } })
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
        :initial-step="initialStep"
        :default-biz="defaultBiz"
        @close="handleClose"
        @step-change="onStepChange"
        @created="onCreated"
      />
    </div>
  </div>
</template>
