<script setup lang="ts">
// 只读分享视图：进度条 + 指标趋势/服务诊断/查看报告 三个 tab，无开始/停止等控制。
// URL: /share?task=<id>&run=<run_id>。run 缺省取该 task 最新一次 run。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Loader2 } from 'lucide-vue-next'
import { useTheme } from '@/composables/useTheme'
import { tasksApi, runsApi } from '@/lib/api'
import RunControlBar from '@/components/tasks/execute/RunControlBar.vue'
import RunDashboard from '@/components/tasks/execute/RunDashboard.vue'
import type { RunEvent, RunMetrics, Task, TaskRun } from '@/types/task'

const route = useRoute()
const { theme } = useTheme()
const isDark = computed(() => theme.value === 'dark')

const task = ref<Task | null>(null)
const run = ref<TaskRun | null>(null)
const metrics = ref<RunMetrics | null>(null)
const events = ref<RunEvent[]>([])
const loading = ref(true)
const error = ref('')

const ACTIVE = ['pre_checking', 'pending', 'running', 'cancelling']
const isActive = computed(() => !!run.value && ACTIVE.includes(run.value.status))
let timer: ReturnType<typeof setInterval> | null = null

async function loadRunData(runId: string) {
  const [r, m, ev] = await Promise.allSettled([
    runsApi.get(runId), runsApi.metrics(runId), runsApi.events(runId),
  ])
  if (r.status === 'fulfilled') run.value = r.value
  if (m.status === 'fulfilled') metrics.value = m.value
  if (ev.status === 'fulfilled') events.value = ev.value
}

async function init() {
  const taskId = Number(route.query.task)
  const runId = (route.query.run as string) || ''
  if (!taskId) { error.value = '缺少 task 参数'; loading.value = false; return }
  try {
    task.value = await tasksApi.get(taskId)
    let rid = runId
    if (!rid) {
      const page = await tasksApi.listRuns(taskId)   // 最新一次 run
      rid = page.results?.[0]?.run_id || ''
    }
    if (rid) await loadRunData(rid)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
  // run 进行中 → 每 3s 刷新进度/指标
  if (isActive.value && run.value?.run_id) {
    timer = setInterval(() => {
      if (!run.value?.run_id) return
      loadRunData(run.value.run_id).then(() => {
        if (!isActive.value && timer) { clearInterval(timer); timer = null }
      })
    }, 3000)
  }
}

onMounted(init)
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <div class="h-screen w-screen flex flex-col p-3 gap-3 overflow-hidden"
       :style="{ background: isDark ? '#0A0A0A' : '#F5F5F7' }">
    <div v-if="loading" class="flex-1 flex items-center justify-center gap-2 text-[13px]"
         :style="{ color: isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.6)' }">
      <Loader2 :size="16" class="animate-spin" /> 加载分享数据…
    </div>
    <div v-else-if="error || !task" class="flex-1 flex items-center justify-center text-[13px]"
         :style="{ color: '#ef4444' }">
      {{ error || '任务不存在' }}
    </div>
    <template v-else>
      <!-- 顶部：任务名 + 只读进度条 -->
      <div class="flex items-center gap-3 flex-shrink-0">
        <span class="text-[14px] font-medium" :style="{ color: isDark ? '#fff' : '#1a1a2e' }">{{ task.title }}</span>
        <span class="text-[11px] px-1.5 py-0.5 rounded" :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)', background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)' }">分享视图 · 只读</span>
      </div>
      <RunControlBar
        :selected-run="run"
        :events="events"
        :task="task"
        :duration-seconds="task.duration_seconds"
        :busy="false"
        hide-controls
        :is-dark="isDark"
      />
      <!-- 数据面板：只露 指标趋势/服务诊断/查看报告 -->
      <div class="flex-1 min-h-0">
        <RunDashboard
          :task="task"
          :run="run"
          :runs="run ? [run] : []"
          :metrics="metrics"
          :environment="null"
          :is-dark="isDark"
          share-mode
        />
      </div>
    </template>
  </div>
</template>
