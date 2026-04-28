<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Motion } from 'motion-v'
import { useRouter } from 'vue-router'
import { useTheme } from '@/composables/useTheme'
import { tasksApi, ApiError } from '@/lib/api'
import type { Task as ApiTask } from '@/types/task'
import { TASKS, type Task as StreamTask } from './perf/data'
import { useRimColor } from './perf/useRimColor'
import ChronosNerve from './perf/ChronosNerve.vue'
import MetricsColumn from './perf/MetricsColumn.vue'
import TemporalColumn from './perf/TemporalColumn.vue'
import TaskContextMenu from './perf/TaskContextMenu.vue'

const { theme } = useTheme()
const isDark = computed(() => theme.value === 'dark')
const rimColor = useRimColor()
const router = useRouter()

const activeBiz = ref('all')
const selectedDate = ref(new Date().getDate())
const focusedTask = ref<string | null>(null)

// Real tasks for the ChronosNerve stream (left column); mock TASKS still feeds
// the metrics / temporal columns where runtime data (rps/p99/...) is needed
// for visual continuity until v1.1 wires up TaskRun.
const realTasks = ref<StreamTask[]>([])

function pad3(n: number) { return n.toString().padStart(3, '0') }

function statusFromApi(s: ApiTask['status']): StreamTask['status'] {
  switch (s) {
    case 'success': return 'success'
    case 'failed': return 'fail'
    case 'running': return 'running'
    case 'configured': return 'configured'
    default: return 'draft'
  }
}

function mapApiTask(t: ApiTask): StreamTask {
  const d = new Date(t.updated_at || t.created_at)
  const hh = d.getHours().toString().padStart(2, '0')
  const mm = d.getMinutes().toString().padStart(2, '0')
  return {
    id: `TSK-${pad3(t.id)}`,
    dbId: t.id,
    title: t.title,
    status: statusFromApi(t.status),
    time: `${hh}:${mm}`,
    date: d.getDate(),
    duration: '',                   // 暂无运行数据
    owner: '',                      // v1 没有 owner 概念
    rps: 0, p99: 0, errorRate: 0,
    vuser: t.virtual_users,
    phases: { prep: 0, exec: 0, analysis: 0 },
    rpsWave: [],
    biz: t.biz_category,
    color: '#3b82f6',
  }
}

async function loadTasks() {
  try {
    const res = await tasksApi.list()
    realTasks.value = res.results.map(mapApiTask)
  } catch (e) {
    // Surface but don't block: 网络错时显示空，让用户走"创建"
    console.error('[performance] failed to load tasks:', e)
    realTasks.value = []
  }
}

onMounted(loadTasks)

function handleCreate() {
  router.push('/performance/tasks')
}

function handleEdit(streamId: string) {
  const t = realTasks.value.find((x) => x.id === streamId)
  if (!t || t.dbId == null) return
  router.push({ path: '/performance/tasks', query: { id: String(t.dbId) } })
}

// ─── Right-click context menu ───────────────────────────────────────────
const ctxMenu = ref<{ x: number; y: number; streamId: string } | null>(null)

function handleContext(streamId: string, x: number, y: number) {
  ctxMenu.value = { x, y, streamId }
}

async function handleDelete() {
  const ctx = ctxMenu.value
  if (!ctx) return
  ctxMenu.value = null
  const t = realTasks.value.find((x) => x.id === ctx.streamId)
  if (!t || t.dbId == null) return
  // Native confirm 足够 v1，不另起对话框组件
  if (!confirm(`确认删除任务 ${t.id}？`)) return
  try {
    await tasksApi.delete(t.dbId)
    await loadTasks()
  } catch (e) {
    alert(e instanceof ApiError ? e.humanMessage : `删除失败：${e}`)
  }
}

// Mock tasks still drive Metrics / Temporal columns (those need runtime metrics
// like rps / p99 / phases that v1 doesn't have yet). Filter mock by selected biz.
const filteredTasks = computed(() =>
  activeBiz.value === 'all' ? TASKS : TASKS.filter((t) => t.biz === activeBiz.value),
)
const taskDates = computed(() => new Set(TASKS.map((t) => t.date)))
const dofActive = computed(() => focusedTask.value !== null)

const panelGlass = computed(() => ({
  background: isDark.value ? 'rgba(255,255,255,0.025)' : 'rgba(255,255,255,0.45)',
  backdropFilter: 'blur(80px)',
  WebkitBackdropFilter: 'blur(80px)',
  borderRadius: '24px',
  boxShadow: `
    inset 0 1px 0 0 rgba(255,255,255,${isDark.value ? 0.06 : 0.6}),
    inset 0 -1px 0 0 rgba(0,0,0,${isDark.value ? 0.08 : 0.02}),
    0 8px 40px rgba(0,0,0,${isDark.value ? 0.2 : 0.06}),
    0 0 0 1px ${rimColor.value}08
  `,
  border: `1px solid ${rimColor.value}${isDark.value ? '0a' : '12'}`,
}))
</script>

<template>
  <!-- 3-column layout (wizard lives on its own route /performance/tasks) -->
  <div class="w-full h-full flex items-stretch gap-2.5 overflow-hidden">
    <!-- Column 1: Chronos Nerve — 真任务列表（替换 mock TASKS） -->
    <div class="flex-shrink-0 overflow-hidden" :style="panelGlass">
      <ChronosNerve
        :is-dark="isDark"
        :tasks="realTasks"
        :rim-color="rimColor"
        :active-biz="activeBiz"
        @focus="(id) => (focusedTask = id)"
        @select-biz="(id) => (activeBiz = id)"
        @create="handleCreate"
        @edit-task="handleEdit"
        @context-task="handleContext"
      />
    </div>

    <TaskContextMenu
      v-if="ctxMenu"
      :is-dark="isDark"
      :visible="!!ctxMenu"
      :x="ctxMenu.x"
      :y="ctxMenu.y"
      @delete="handleDelete"
      @close="ctxMenu = null"
    />

      <!-- Column 2: Metrics & Consumption -->
      <Motion
        class="flex-1 min-w-0 overflow-hidden"
        :style="panelGlass"
        :animate="{
          filter: dofActive ? 'blur(1px)' : 'blur(0px)',
          opacity: dofActive ? 0.8 : 1,
        }"
        :transition="{ duration: 0.4 }"
      >
        <MetricsColumn
          :is-dark="isDark"
          :tasks="filteredTasks"
          :focused-task="focusedTask"
          :rim-color="rimColor"
          :selected-date="selectedDate"
          @select-date="(d) => (selectedDate = d)"
        />
      </Motion>

      <!-- Column 3: Temporal & Personnel -->
      <Motion
        class="flex-shrink-0 overflow-hidden"
        :style="panelGlass"
        :animate="{
          filter: dofActive ? 'blur(1.5px)' : 'blur(0px)',
          opacity: dofActive ? 0.75 : 1,
        }"
        :transition="{ duration: 0.4 }"
      >
        <TemporalColumn
          :is-dark="isDark"
          :selected-date="selectedDate"
          :rim-color="rimColor"
          :task-dates="taskDates"
          :focused-task="focusedTask"
          :tasks="filteredTasks"
          @select-date="(d) => (selectedDate = d)"
        />
      </Motion>
  </div>
</template>
