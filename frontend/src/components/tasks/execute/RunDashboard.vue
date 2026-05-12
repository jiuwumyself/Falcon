<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  Activity, BarChart3, AlertOctagon, Server, GitBranch, Cpu, FileText, FileSearch,
} from 'lucide-vue-next'
import type { RunMetrics, Task, TaskRun } from '@/types/task'
import TrendsTab from './dashboard/TrendsTab.vue'
import SamplersTab from './dashboard/SamplersTab.vue'
import ErrorsTab from './dashboard/ErrorsTab.vue'
import ServicePanelsTab from './dashboard/ServicePanelsTab.vue'
import TracePanelsTab from './dashboard/TracePanelsTab.vue'
import JvmTab from './dashboard/JvmTab.vue'
import PreCheckTab from './dashboard/PreCheckTab.vue'
import ReportTab from './dashboard/ReportTab.vue'

const props = defineProps<{
  task: Task
  run: TaskRun | null
  metrics: RunMetrics | null
  isDark: boolean
}>()

type TabId = 'trends' | 'samplers' | 'errors' | 'service' | 'trace' | 'jvm' | 'precheck' | 'report'

const TABS: { id: TabId; label: string; icon: any }[] = [
  { id: 'trends', label: '指标趋势', icon: Activity },
  { id: 'samplers', label: '接口统计', icon: BarChart3 },
  { id: 'errors', label: '错误明细', icon: AlertOctagon },
  // 「运行时间轴」并入 RunControlBar 进度条（phase 染色 + 事件锚点），tab 删除
  { id: 'service', label: '服务面板', icon: Server },
  { id: 'trace', label: '链路面板', icon: GitBranch },
  // G4：JVM tab v1（plan §4.5），位于"链路面板"之后；dump 按钮 disabled 等 Arthas
  { id: 'jvm', label: 'JVM', icon: Cpu },
  { id: 'precheck', label: '预检日志', icon: FileText },
  { id: 'report', label: '查看报告', icon: FileSearch },
]

const active = ref<TabId>('trends')

// SamplersTab 用：终态时定格不再轮询
const TERMINAL: TaskRun['status'][] = [
  'pre_check_failed', 'success', 'failed', 'timeout', 'cancelled',
]
const isTerminal = computed(() =>
  !!props.run && (TERMINAL as string[]).includes(props.run.status),
)
</script>

<template>
  <div class="flex flex-col h-full min-h-0 rounded-xl"
       :style="{
         background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)',
         border: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
       }">
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
                 :task="task"
                 :run="run"
                 :metrics="metrics" :is-dark="isDark" />
      <SamplersTab v-else-if="active === 'samplers'"
                   :run-id="run?.run_id || null"
                   :is-terminal="isTerminal"
                   :is-dark="isDark" />
      <ErrorsTab v-else-if="active === 'errors'"
                 :run="run"
                 :run-id="run?.run_id || null"
                 :is-dark="isDark" />
      <ServicePanelsTab v-else-if="active === 'service'"
                        :task="task" :run="run" :is-dark="isDark" />
      <TracePanelsTab v-else-if="active === 'trace'"
                      :task="task" :run="run" :is-dark="isDark" />
      <JvmTab v-else-if="active === 'jvm'"
              :task="task" :run="run" :is-dark="isDark" />
      <PreCheckTab v-else-if="active === 'precheck'"
                   :log="run?.pre_check_log || ''"
                   :is-dark="isDark" />
      <ReportTab v-else-if="active === 'report'"
                 :run="run" :is-dark="isDark" />
    </div>
  </div>
</template>
