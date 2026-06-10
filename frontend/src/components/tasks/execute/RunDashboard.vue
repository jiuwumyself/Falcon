<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  Activity, BarChart3, Stethoscope, FileText, FileSearch, Share2,
} from 'lucide-vue-next'
import type { Environment, RunMetrics, Task, TaskRun } from '@/types/task'
import RunPlanSummary from './RunPlanSummary.vue'
import RunHistoryDropdown from './RunHistoryDropdown.vue'
import TrendsTab from './dashboard/TrendsTab.vue'
import SamplersTab from './dashboard/SamplersTab.vue'
import DiagnosisTab from './dashboard/DiagnosisTab.vue'
import RunLogTab from './dashboard/RunLogTab.vue'
import ReportTab from './dashboard/ReportTab.vue'

const props = defineProps<{
  task: Task
  run: TaskRun | null
  runs: TaskRun[]
  metrics: RunMetrics | null
  environment: Environment | null
  isDark: boolean
  shareMode?: boolean   // 分享视图：只留 指标趋势/服务诊断/查看报告，藏历史/分享/任务简介
}>()

defineEmits<{
  (e: 'select', runId: string): void
  (e: 'run-deleted', runId: string): void
}>()

type TabId = 'trends' | 'samplers' | 'diagnosis' | 'runlog' | 'report'

const TABS: { id: TabId; label: string; icon: any }[] = [
  { id: 'trends', label: '指标趋势', icon: Activity },
  // 服务面板 + 链路面板 + JVM 合并为「服务诊断」单页（拓扑+Pod时序+Pinpoint事务/异常/慢URL/线程/连接池）
  { id: 'diagnosis', label: '服务诊断', icon: Stethoscope },
  // 「错误明细」已并入「接口统计」（donut 错误构成 + 展开行 code+message+count）
  { id: 'samplers', label: '接口统计', icon: BarChart3 },
  { id: 'report', label: '查看报告', icon: FileSearch },
  { id: 'runlog', label: '运行日志', icon: FileText },
]

const active = ref<TabId>('trends')

// 分享视图露：指标趋势 / 服务诊断 / 接口统计 / 查看报告（顺序随 TABS，报告在最后）
const SHARE_TABS: TabId[] = ['trends', 'diagnosis', 'samplers', 'report']
const visibleTabs = computed(() =>
  props.shareMode ? TABS.filter((t) => SHARE_TABS.includes(t.id)) : TABS)

// 分享链接：当前选中的 run（含从历史选的）→ 带 run；没有就只带 task（分享页取最新）
function onShare() {
  const url = `${window.location.origin}/share?task=${props.task.id}`
    + (props.run?.run_id ? `&run=${props.run.run_id}` : '')
  try { navigator.clipboard?.writeText(url) } catch { /* 忽略剪贴板失败 */ }
  window.open(url, '_blank', 'noopener')
}

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
        v-for="t in visibleTabs"
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

      <template v-if="!shareMode">
        <!-- 历史下拉：紧跟「查看报告」之后 -->
        <RunHistoryDropdown
          :runs="runs"
          :selected-run="run"
          :is-dark="isDark"
          @select="$emit('select', $event)"
          @run-deleted="$emit('run-deleted', $event)"
        />
        <!-- 分享：开只读视图（指标趋势/服务诊断/查看报告 + 进度条，无控制按钮）+ 复制链接 -->
        <button
          class="flex items-center gap-1 px-2.5 py-1 text-[12px] cursor-pointer flex-shrink-0 rounded-md ml-1"
          :style="{ color: isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.6)' }"
          title="分享只读视图（复制链接 + 新窗口打开）"
          @click="onShare"
        >
          <Share2 :size="13" />分享
        </button>

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
      </template>
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
      <DiagnosisTab v-else-if="active === 'diagnosis'"
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
