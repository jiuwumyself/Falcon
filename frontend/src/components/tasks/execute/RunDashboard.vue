<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  Activity, BarChart3, Server, GitBranch, Cpu, FileText, FileSearch,
} from 'lucide-vue-next'
import type { Environment, RunMetrics, Task, TaskRun } from '@/types/task'
import RunPlanSummary from './RunPlanSummary.vue'
import RunHistoryDropdown from './RunHistoryDropdown.vue'
import TrendsTab from './dashboard/TrendsTab.vue'
import SamplersTab from './dashboard/SamplersTab.vue'
import ServicePanelsTab from './dashboard/ServicePanelsTab.vue'
import TracePanelsTab from './dashboard/TracePanelsTab.vue'
import JvmTab from './dashboard/JvmTab.vue'
import RunLogTab from './dashboard/RunLogTab.vue'
import ReportTab from './dashboard/ReportTab.vue'

const props = defineProps<{
  task: Task
  run: TaskRun | null
  runs: TaskRun[]
  metrics: RunMetrics | null
  environment: Environment | null
  isDark: boolean
}>()

defineEmits<{
  (e: 'select', runId: string): void
  (e: 'run-deleted', runId: string): void
}>()

type TabId = 'trends' | 'samplers' | 'service' | 'trace' | 'jvm' | 'runlog' | 'report'

const TABS: { id: TabId; label: string; icon: any }[] = [
  { id: 'trends', label: '指标趋势', icon: Activity },
  // 「错误明细」已并入「接口统计」（donut 错误构成 + 展开行 code+message+count）
  { id: 'samplers', label: '接口统计', icon: BarChart3 },
  // 「运行时间轴」并入 RunControlBar 进度条（phase 染色 + 事件锚点），tab 删除
  { id: 'service', label: '服务面板', icon: Server },
  { id: 'trace', label: '链路面板', icon: GitBranch },
  // G4：JVM tab v1（plan §4.5），位于"链路面板"之后；dump 按钮 disabled 等 Arthas
  { id: 'jvm', label: 'JVM', icon: Cpu },
  { id: 'runlog', label: '运行日志', icon: FileText },
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

      <!-- 历史下拉：紧跟「查看报告」之后 -->
      <RunHistoryDropdown
        :runs="runs"
        :selected-run="run"
        :is-dark="isDark"
        @select="$emit('select', $event)"
        @run-deleted="$emit('run-deleted', $event)"
      />

      <!-- 标签行末尾：任务简介 chips（｜分隔；场景徽章已去掉，看 Trends 切换器）-->
      <div
        class="ml-auto flex items-center pl-3 flex-shrink-0"
        :style="{ borderLeft: `1px solid ${isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)'}` }"
      >
        <RunPlanSummary
          :task="task"
          :selected-run="run"
          :environment="environment"
          :is-dark="isDark"
          embedded
        />
      </div>
    </div>

    <!-- 当前 tab 内容（占满剩余高度）-->
    <div class="flex-1 min-h-0">
      <TrendsTab v-if="active === 'trends'"
                 :task="task"
                 :run="run"
                 :runs="runs"
                 :metrics="metrics" :is-dark="isDark" />
      <SamplersTab v-else-if="active === 'samplers'"
                   :run="run"
                   :run-id="run?.run_id || null"
                   :is-terminal="isTerminal"
                   :is-dark="isDark" />
      <ServicePanelsTab v-else-if="active === 'service'"
                        :task="task" :run="run" :is-dark="isDark" />
      <TracePanelsTab v-else-if="active === 'trace'"
                      :task="task" :run="run" :is-dark="isDark" />
      <JvmTab v-else-if="active === 'jvm'"
              :task="task" :run="run" :is-dark="isDark" />
      <RunLogTab v-else-if="active === 'runlog'"
                 :run="run"
                 :is-terminal="isTerminal"
                 :is-dark="isDark" />
      <ReportTab v-else-if="active === 'report'"
                 :run="run" :is-dark="isDark" />
    </div>
  </div>
</template>
