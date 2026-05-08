<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ApiError, runsApi, tasksApi } from '@/lib/api'
import type { RunMetrics, Task, TaskRun } from '@/types/task'
import RunControlBar from './execute/RunControlBar.vue'
import RunDashboard from './execute/RunDashboard.vue'
import StartRunModal from './execute/StartRunModal.vue'

const props = defineProps<{
  task: Task
  isDark: boolean
}>()

const runs = ref<TaskRun[]>([])
const selectedRunId = ref<string | null>(null)
const metrics = ref<RunMetrics | null>(null)
const busy = ref(false)
const errorMessage = ref('')
const startModalOpen = ref(false)

let pollTimer: ReturnType<typeof setInterval> | null = null
const POLL_INTERVAL_MS = 3000

const activeStatuses = ['pre_checking', 'pending', 'running', 'cancelling']

const selectedRun = computed<TaskRun | null>(() => {
  if (!selectedRunId.value) return null
  return runs.value.find((r) => r.run_id === selectedRunId.value) || null
})

const isPolling = computed(() =>
  !!selectedRun.value && activeStatuses.includes(selectedRun.value.status),
)

async function fetchRuns(autoSelect = true) {
  try {
    const page = await tasksApi.listRuns(props.task.id)
    runs.value = page.results
    if (autoSelect && !selectedRunId.value && runs.value.length) {
      selectedRunId.value = runs.value[0].run_id
    }
  } catch (e) {
    console.error('listRuns 失败', e)
  }
}

async function fetchMetrics() {
  if (!selectedRunId.value) {
    metrics.value = null
    return
  }
  try {
    const data = await runsApi.metrics(selectedRunId.value)
    metrics.value = data
    if (data.run) {
      const idx = runs.value.findIndex((r) => r.run_id === data.run.run_id)
      if (idx >= 0) runs.value[idx] = data.run
      else runs.value.unshift(data.run)
    }
  } catch (e) {
    console.error('metrics 失败', e)
  }
}

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    await fetchMetrics()
    if (selectedRun.value && !activeStatuses.includes(selectedRun.value.status)) {
      stopPolling()
    }
  }, POLL_INTERVAL_MS)
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

watch(isPolling, (active) => {
  if (active) startPolling()
  else stopPolling()
})

watch(selectedRunId, () => {
  metrics.value = null
  fetchMetrics()
})

// ─── 控制条事件 ─────────────────────────────────

function onStartClick() {
  // 不直接启动，先弹 modal 选机器（必选）
  errorMessage.value = ''
  startModalOpen.value = true
}

async function onConfirmStart(loadGeneratorIds: number[]) {
  startModalOpen.value = false
  busy.value = true
  errorMessage.value = ''
  try {
    const run = await tasksApi.startRun(props.task.id, {
      load_generator_ids: loadGeneratorIds,
    })
    runs.value.unshift(run)
    selectedRunId.value = run.run_id
    await fetchMetrics()
  } catch (e) {
    if (e instanceof ApiError) {
      errorMessage.value = e.status === 409
        ? '该任务已有运行中的 run，请先停止'
        : e.humanMessage
    } else {
      errorMessage.value = String(e)
    }
  } finally {
    busy.value = false
  }
}

async function onStop() {
  if (!selectedRunId.value) return
  busy.value = true
  errorMessage.value = ''
  try {
    const run = await runsApi.cancel(selectedRunId.value)
    const idx = runs.value.findIndex((r) => r.run_id === run.run_id)
    if (idx >= 0) runs.value[idx] = run
  } catch (e) {
    if (e instanceof ApiError) errorMessage.value = e.humanMessage
  } finally {
    busy.value = false
  }
}

function onViewReport() {
  if (!selectedRunId.value) return
  window.open(runsApi.reportUrl(selectedRunId.value), '_blank')
}

function onSelectRun(rid: string) {
  selectedRunId.value = rid
}

onMounted(async () => {
  await fetchRuns(true)
  const active = runs.value.find((r) => activeStatuses.includes(r.status))
  if (active) selectedRunId.value = active.run_id
  await fetchMetrics()
})

onUnmounted(stopPolling)
</script>

<template>
  <div class="h-full flex flex-col gap-3 min-h-0">
    <!-- 错误条 -->
    <div
      v-if="errorMessage"
      class="rounded-lg px-3 py-2 text-[12.5px] flex-shrink-0"
      :style="{
        background: 'rgba(239,68,68,0.1)',
        border: '1px solid rgba(239,68,68,0.25)',
        color: '#ef4444',
      }"
    >
      {{ errorMessage }}
    </div>

    <!-- 顶部控制条（一行紧凑）-->
    <RunControlBar
      :selected-run="selectedRun"
      :runs="runs"
      :duration-seconds="task.duration_seconds || 0"
      :busy="busy"
      :is-dark="isDark"
      @start="onStartClick"
      @stop="onStop"
      @view-report="onViewReport"
      @select="onSelectRun"
    />

    <!-- 终态失败原因（run.error_message 在终态非空时显示，比 jmeter.log 更直白） -->
    <div
      v-if="selectedRun && (['failed','timeout','pre_check_failed'].includes(selectedRun.status)) && selectedRun.error_message"
      class="rounded-lg px-3 py-2 text-[12px] flex-shrink-0"
      :style="{
        background: 'rgba(239,68,68,0.08)',
        border: '1px solid rgba(239,68,68,0.22)',
        color: '#ef4444',
      }"
    >
      <span class="font-medium">失败原因：</span>{{ selectedRun.error_message }}
    </div>

    <!-- 数据 dashboard：占满剩余高度，内部 tab 切换数据面板 -->
    <div class="flex-1 min-h-0">
      <RunDashboard
        :task="task"
        :run="selectedRun"
        :metrics="metrics"
        :is-dark="isDark"
      />
    </div>

    <!-- 开始压测弹窗（必选压力源）-->
    <StartRunModal
      :open="startModalOpen"
      :vusers="task.virtual_users"
      :is-dark="isDark"
      @close="startModalOpen = false"
      @confirm="onConfirmStart"
    />
  </div>
</template>
