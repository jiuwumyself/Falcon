<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { AlertTriangle } from 'lucide-vue-next'
import { ApiError, runsApi, tasksApi } from '@/lib/api'
import type { Environment, RunEvent, RunMetrics, Task, TaskRun } from '@/types/task'
import RunControlBar from './execute/RunControlBar.vue'
import RunDashboard from './execute/RunDashboard.vue'
import StartRunModal from './execute/StartRunModal.vue'

const props = defineProps<{
  task: Task
  isDark: boolean
}>()

// 跳回上一步（Step 2 config）的事件，stale banner 里的链接触发
// 父组件 TaskCreateWizard 监听，切 currentStep
defineEmits<{
  (e: 'jumpStep', stepId: 'upload' | 'config' | 'execute' | 'analyze' | 'report'): void
}>()

const runs = ref<TaskRun[]>([])
const selectedRunId = ref<string | null>(null)
const metrics = ref<RunMetrics | null>(null)
// § 12 S1：事件锚点（融合到 RunControlBar 进度条上，跟 task.duration 共享时间刻度）
const events = ref<RunEvent[]>([])
// RunPlanSummary 显示环境名 + hosts 数用；按 task.environment 反查
const environments = ref<Environment[]>([])
const taskEnvironment = computed<Environment | null>(() => {
  if (!props.task.environment) return null
  return environments.value.find((e) => e.id === props.task.environment) || null
})
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

async function fetchRuns(autoSelect = false) {
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

async function fetchEvents() {
  if (!selectedRunId.value) {
    events.value = []
    return
  }
  try {
    events.value = await runsApi.events(selectedRunId.value)
  } catch {
    events.value = []
  }
}

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    await fetchMetrics()
    void fetchEvents()  // 事件锚点轻量，跟 metrics 同节奏轮询，能看到 early abort 实时触发
    if (selectedRun.value && !activeStatuses.includes(selectedRun.value.status)) {
      stopPolling()
      // 终态再拉一次：_record_phase_anchors_for_run 在 _on_finish 后写 phase 三事件 + first_error
      void fetchEvents()
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
  events.value = []
  fetchMetrics()
  void fetchEvents()
})

// ─── 控制条事件 ─────────────────────────────────

function onStartClick() {
  // 不直接启动，先弹 modal 选机器（必选）
  errorMessage.value = ''
  // 兜底拦：banner 已显示 stale 警告 + RunControlBar 按钮也置灰；但用户从 dashboard
  // 其他位置触发 emit 时这里再拦一道，避免起 run 被后端 409 才返
  if (props.task.config_stale) {
    errorMessage.value = '线程组配置已过期：你在 Step 1 改过 TG 启用状态或类型，请回 Step 2 重新保存后再开始'
    return
  }
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
      // 409 有多种原因：已有活跃 run / 线程组配置过期 等。后端 detail 文案已经
      // 准确描述（humanMessage 会把 `{"detail": "..."}` 解析出来），不要前端再
      // hardcode 文案覆盖——之前一律显示"该任务已在运行"导致 stale 拦截误报。
      errorMessage.value = e.humanMessage
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

function onSelectRun(rid: string) {
  selectedRunId.value = rid
}

async function onRunDeleted(rid: string) {
  // 删的是当前选中的 → 切到最近一个非删 run（或 null）
  const wasSelected = selectedRunId.value === rid
  await fetchRuns(false)
  if (wasSelected) {
    selectedRunId.value = runs.value[0]?.run_id ?? null
    await fetchMetrics()
  }
}

onMounted(async () => {
  // autoSelect=false：进来不自动选最新 terminal run；只在有 active run 时选中（监控进度合理）。
  // 都是终态时 selectedRunId 保持 null → 空盘灰底 + 按钮文案「开始」。
  await fetchRuns(false)
  const active = runs.value.find((r) => activeStatuses.includes(r.status))
  if (active) selectedRunId.value = active.run_id
  await fetchMetrics()
  void fetchEvents()
  // 拉环境列表给 RunPlanSummary 显示环境名 + hosts 数；失败静默
  try {
    environments.value = await tasksApi.environments()
  } catch {
    environments.value = []
  }
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

    <!-- Step 2 配置过期 banner：用户在 Step 1 切了 TG enabled/kind 但没回 Step 2
         重新保存。banner 黄色（警告 ≠ 错误），点链接回 Step 2 -->
    <div
      v-if="task.config_stale"
      class="rounded-lg px-3 py-2 text-[12.5px] flex-shrink-0 flex items-start gap-2"
      :style="{
        background: 'rgba(245,158,11,0.1)',
        border: '1px solid rgba(245,158,11,0.28)',
        color: '#f59e0b',
      }"
    >
      <AlertTriangle :size="14" class="mt-0.5 flex-shrink-0" />
      <div class="flex-1">
        <div class="font-medium mb-0.5">线程组配置已过期，无法开始</div>
        <div class="text-[11.5px] opacity-90">
          你在 Step 1 改过线程组的启用状态或类型，但 Step 2 保存的还是旧版本。
          <a
            class="underline cursor-pointer ml-1"
            @click="$emit('jumpStep', 'config')"
          >回 Step 2 重新保存</a>
          后再开始执行。
        </div>
      </div>
    </div>

    <!-- 顶部控制条（两行：上=控制条 / 下=任务简介）+ 事件锚点叠在进度条上 -->
    <RunControlBar
      :selected-run="selectedRun"
      :runs="runs"
      :events="events"
      :task="task"
      :environment="taskEnvironment"
      :duration-seconds="task.duration_seconds || 0"
      :busy="busy"
      :start-disabled="task.config_stale"
      :is-dark="isDark"
      @start="onStartClick"
      @stop="onStop"
      @select="onSelectRun"
      @run-deleted="onRunDeleted"
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
      :tg-count="(task.thread_groups_config || []).length"
      :is-dark="isDark"
      @close="startModalOpen = false"
      @confirm="onConfirmStart"
    />
  </div>
</template>
