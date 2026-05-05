<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ApiError, runsApi, tasksApi } from '@/lib/api'
import type { Environment, RunMetrics, Task, TaskRun } from '@/types/task'
import RunStatusCard from './execute/RunStatusCard.vue'
import RunHistoryList from './execute/RunHistoryList.vue'
import RunMetricsCharts from './execute/RunMetricsCharts.vue'
import PreCheckPanel from './execute/PreCheckPanel.vue'
import RunKpiHero from './execute/RunKpiHero.vue'
import RunPlanSummary from './execute/RunPlanSummary.vue'

const props = defineProps<{
  task: Task
  isDark: boolean
}>()

const runs = ref<TaskRun[]>([])
const selectedRunId = ref<string | null>(null)
const metrics = ref<RunMetrics | null>(null)
const busy = ref(false)
const errorMessage = ref('')
const environments = ref<Environment[]>([])

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

const currentEnvironment = computed<Environment | null>(() => {
  const id = props.task.environment
  if (id == null) return null
  return environments.value.find((e) => e.id === id) || null
})

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

async function fetchEnvironments() {
  try {
    environments.value = await tasksApi.environments()
  } catch (e) {
    // 环境拉不到不阻塞主流程；plan 摘要会显示"无环境"
    console.error('environments 失败', e)
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

async function onStart() {
  errorMessage.value = ''
  busy.value = true
  try {
    const run = await tasksApi.startRun(props.task.id)
    runs.value.unshift(run)
    selectedRunId.value = run.run_id
    await fetchMetrics()
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 409) {
        errorMessage.value = '该任务已有运行中的 run，请先取消'
      } else {
        errorMessage.value = e.humanMessage
      }
    } else {
      errorMessage.value = String(e)
    }
  } finally {
    busy.value = false
  }
}

async function onCancel() {
  if (!selectedRunId.value) return
  busy.value = true
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

onMounted(async () => {
  await Promise.all([fetchRuns(true), fetchEnvironments()])
  const active = runs.value.find((r) => activeStatuses.includes(r.status))
  if (active) selectedRunId.value = active.run_id
  await fetchMetrics()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <div class="h-full flex flex-col gap-4">
    <!-- 错误条 -->
    <div
      v-if="errorMessage"
      class="rounded-lg px-3 py-2 text-[12.5px]"
      :style="{
        background: 'rgba(239,68,68,0.1)',
        border: '1px solid rgba(239,68,68,0.25)',
        color: '#ef4444',
      }"
    >
      {{ errorMessage }}
    </div>

    <!-- 单列竖直堆叠：状态条 → 历史 ribbon → KPI Hero → Plan 摘要 → 趋势图 → 预检日志 -->
    <div class="flex-1 flex flex-col gap-3 min-h-0 overflow-y-auto pr-1">
      <RunStatusCard
        :run="selectedRun"
        :is-dark="isDark"
        :busy="busy"
        @start="onStart"
        @cancel="onCancel"
        @view-report="onViewReport"
      />
      <RunHistoryList
        :runs="runs"
        :selected-run-id="selectedRunId"
        :is-dark="isDark"
        @select="selectedRunId = $event"
      />
      <RunKpiHero
        :task="task"
        :run="selectedRun"
        :metrics="metrics"
        :is-dark="isDark"
      />
      <RunPlanSummary
        :task="task"
        :environment="currentEnvironment"
        :is-dark="isDark"
      />
      <RunMetricsCharts :metrics="metrics" :is-dark="isDark" />
      <PreCheckPanel
        v-if="selectedRun?.pre_check_log"
        :log="selectedRun.pre_check_log"
        :is-dark="isDark"
      />
    </div>
  </div>
</template>
