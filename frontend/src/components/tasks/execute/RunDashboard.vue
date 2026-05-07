<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  Activity, BarChart3, AlertOctagon, Clock, Server, GitBranch, FileText,
} from 'lucide-vue-next'
import type { RunMetrics, Task, TaskRun } from '@/types/task'
import TrendsTab from './dashboard/TrendsTab.vue'
import SamplersTab from './dashboard/SamplersTab.vue'
import ErrorsTab from './dashboard/ErrorsTab.vue'
import TimelineTab from './dashboard/TimelineTab.vue'
import ServicePanelsTab from './dashboard/ServicePanelsTab.vue'
import TracePanelsTab from './dashboard/TracePanelsTab.vue'
import PreCheckTab from './dashboard/PreCheckTab.vue'

const props = defineProps<{
  task: Task
  run: TaskRun | null
  metrics: RunMetrics | null
  isDark: boolean
}>()

type TabId = 'trends' | 'samplers' | 'errors' | 'timeline' | 'service' | 'trace' | 'precheck'

const TABS: { id: TabId; label: string; icon: any }[] = [
  { id: 'trends', label: '指标趋势', icon: Activity },
  { id: 'samplers', label: '接口统计', icon: BarChart3 },
  { id: 'errors', label: '错误明细', icon: AlertOctagon },
  { id: 'timeline', label: '运行时间轴', icon: Clock },
  { id: 'service', label: '服务面板', icon: Server },
  { id: 'trace', label: '链路面板', icon: GitBranch },
  { id: 'precheck', label: '预检日志', icon: FileText },
]

const active = ref<TabId>('trends')

// 终态决定是否显示「完成态」KPI 数据
const TERMINAL: TaskRun['status'][] = [
  'pre_check_failed', 'success', 'failed', 'timeout', 'cancelled',
]
const isTerminal = computed(() =>
  !!props.run && (TERMINAL as string[]).includes(props.run.status),
)

function fmtNum(n: number, digits = 0): string {
  if (n == null || Number.isNaN(n)) return '—'
  if (n >= 10000) return `${(n / 1000).toFixed(1)}k`
  return digits ? n.toFixed(digits) : Math.round(n).toString()
}

const kpis = computed(() => {
  const r = props.run
  return [
    { label: '总请求', value: r ? fmtNum(r.total_requests) : '—', color: '#3b82f6' },
    { label: '平均 RPS', value: r ? fmtNum(r.avg_rps, 1) : '—', color: '#10b981' },
    { label: 'P99', value: r ? `${fmtNum(r.p99_ms)} ms` : '—', color: '#a78bfa' },
    {
      label: '错误率',
      value: r ? `${(r.error_rate || 0).toFixed(2)}%` : '—',
      color: (r?.error_rate || 0) >= 1 ? '#ef4444' : '#10b981',
    },
  ]
})
</script>

<template>
  <div class="flex flex-col h-full min-h-0 rounded-xl"
       :style="{
         background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)',
         border: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
       }">
    <!-- 顶部 KPI 横条 -->
    <div class="grid grid-cols-4 gap-2 p-3"
         :style="{
           borderBottom: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
         }">
      <div v-for="k in kpis" :key="k.label" class="flex flex-col">
        <span class="text-[10px] uppercase tracking-wider"
              :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.5)' }">
          {{ k.label }}
        </span>
        <span class="text-[20px] mt-0.5"
              :style="{ color: k.color, fontVariantNumeric: 'tabular-nums' }">
          {{ k.value }}
        </span>
      </div>
    </div>

    <!-- Tabs 切换器 -->
    <div class="flex items-center gap-0 px-3 overflow-x-auto"
         :style="{
           borderBottom: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
         }">
      <button
        v-for="t in TABS"
        :key="t.id"
        class="flex items-center gap-1.5 px-3 py-2 text-[12px] cursor-pointer flex-shrink-0"
        :style="{
          color: active === t.id
            ? (isDark ? '#fff' : '#1a1a2e')
            : (isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.55)'),
          borderBottom: `2px solid ${active === t.id ? '#3b82f6' : 'transparent'}`,
        }"
        @click="active = t.id"
      >
        <component :is="t.icon" :size="12" />
        {{ t.label }}
      </button>
    </div>

    <!-- 当前 tab 内容（占满剩余高度）-->
    <div class="flex-1 min-h-0">
      <TrendsTab v-if="active === 'trends'"
                 :metrics="metrics" :is-dark="isDark" />
      <SamplersTab v-else-if="active === 'samplers'"
                   :run-id="run?.run_id || null"
                   :is-terminal="isTerminal"
                   :is-dark="isDark" />
      <ErrorsTab v-else-if="active === 'errors'"
                 :run-id="run?.run_id || null"
                 :is-dark="isDark" />
      <TimelineTab v-else-if="active === 'timeline'"
                   :run="run" :is-dark="isDark" />
      <ServicePanelsTab v-else-if="active === 'service'"
                        :task="task" :run="run" :is-dark="isDark" />
      <TracePanelsTab v-else-if="active === 'trace'"
                      :task="task" :run="run" :is-dark="isDark" />
      <PreCheckTab v-else-if="active === 'precheck'"
                   :log="run?.pre_check_log || ''"
                   :is-dark="isDark" />
    </div>
  </div>
</template>
