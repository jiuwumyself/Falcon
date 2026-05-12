<script setup lang="ts">
import { computed, ref } from 'vue'
import { Layers, Users, Clock, Globe, FileSpreadsheet, AlertTriangle } from 'lucide-vue-next'
import type { Environment, Task, TaskRun } from '@/types/task'
import { plannedThreads, plannedDurationSec, formatDuration, hasOnlyArrivals, targetRps } from '@/lib/planSummary'
import { scenarioById, inferScenarioFromKind } from '@/components/tasks/configStageCtx'

const props = defineProps<{
  task: Task
  environment: Environment | null
  isDark: boolean
  // 嵌入到 RunControlBar 卡片内时不渲染外层卡片背景/边框，只渲染 chips
  embedded?: boolean
  // 当前选中的 run；优先用它的 thread_groups_config_snapshot 显示"当时配置"。
  // 没选 / 旧 run 没快照时回退到 task.thread_groups_config（当前配置）。
  selectedRun?: TaskRun | null
}>()

// 数据源切换：snapshot 优先，旧 run / 无 run 时回退当前 task 配置
const effectiveCfgs = computed(() => {
  const snap = props.selectedRun?.thread_groups_config_snapshot
  if (snap && snap.length > 0) return snap
  return props.task.thread_groups_config || []
})

const tgCount = computed(() => effectiveCfgs.value.length)
const threadsTotal = computed(() => plannedThreads(effectiveCfgs.value))
const durationSec = computed(() => plannedDurationSec(effectiveCfgs.value))
const onlyArrivals = computed(() => hasOnlyArrivals(effectiveCfgs.value))
const rpsTarget = computed(() => targetRps(effectiveCfgs.value))
const csvCount = computed(() => (props.task.csv_bindings || []).length)

const showTgPop = ref(false)

// 给 TG hover popover 用：每个 TG 解析出场景 dot + label
const tgDetails = computed(() =>
  effectiveCfgs.value.map((c) => {
    const sid = c.scenario || inferScenarioFromKind(c.kind)
    const sce = scenarioById(sid)
    return { path: c.path, label: sce.label, color: sce.color, kind: c.kind }
  }),
)

// 主场景徽章：取 effectiveCfgs 第一个 TG 的场景；多 TG 时附 +N 提示
const scenario = computed(() => {
  const first = effectiveCfgs.value[0]
  if (!first) return null
  const sid = first.scenario || inferScenarioFromKind(first.kind)
  return scenarioById(sid)
})
const extraN = computed(() => Math.max(0, effectiveCfgs.value.length - 1))

// 变化提示：snapshot 跟当前 task 不一致 → 显示"脚本或线程组配置已变化"
// jmx_hash 变（重新上传 / Step 1 改 enabled/testname）或 thread_groups_config 变
// （Step 2 改场景 / 参数）任一命中即提示。文案统一不区分。
const hasChanged = computed(() => {
  const r = props.selectedRun
  if (!r) return false
  if (r.jmx_hash_snapshot && r.jmx_hash_snapshot !== (props.task.jmx_hash || '')) return true
  const snap = r.thread_groups_config_snapshot || []
  const curr = props.task.thread_groups_config || []
  return JSON.stringify(snap) !== JSON.stringify(curr)
})
</script>

<template>
  <div
    v-if="tgCount > 0"
    :class="embedded
      ? 'flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px]'
      : 'rounded-xl px-4 py-2.5 flex flex-wrap items-center gap-x-4 gap-y-2 text-[12.5px]'"
    :style="embedded
      ? {}
      : {
          background: isDark ? 'rgba(255,255,255,0.025)' : 'rgba(255,255,255,0.55)',
          border: isDark ? '1px solid rgba(255,255,255,0.05)' : '1px solid rgba(0,0,0,0.04)',
        }"
  >
    <!-- 场景徽章（从 KpiBar 搬过来）：主场景 + 多 TG 时显示 +N。
         hover 触发 showTgPop 跟下面"N 个 TG" 共用 popover，省一份代码。 -->
    <span
      v-if="scenario"
      class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] flex-shrink-0 cursor-default"
      :style="{
        background: `${scenario.color}1f`,
        color: scenario.color,
        border: `1px solid ${scenario.color}33`,
      }"
      @mouseenter="showTgPop = true"
      @mouseleave="showTgPop = false"
    >
      <component :is="scenario.icon" :size="11" />
      {{ scenario.label }}
      <span v-if="extraN > 0" class="opacity-60 ml-0.5">+{{ extraN }}</span>
    </span>

    <!-- TG 数（hover 弹详情） -->
    <div
      class="relative inline-flex items-center gap-1.5 cursor-default"
      @mouseenter="showTgPop = true"
      @mouseleave="showTgPop = false"
    >
      <Layers :size="13" :color="isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.45)'" />
      <span :style="{ color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.75)' }">
        <b class="font-semibold">{{ tgCount }}</b> 个 TG
      </span>
      <div
        v-if="showTgPop"
        class="absolute left-0 top-full mt-2 z-30 min-w-[200px] rounded-lg p-2.5 shadow-xl"
        :style="{
          background: isDark ? 'rgba(20,20,30,0.97)' : 'rgba(255,255,255,0.98)',
          border: isDark ? '1px solid rgba(255,255,255,0.08)' : '1px solid rgba(0,0,0,0.08)',
          backdropFilter: 'blur(20px)',
        }"
      >
        <div
          class="text-[10px] uppercase tracking-wider mb-1.5"
          :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
        >启用的 ThreadGroup</div>
        <div
          v-for="tg in tgDetails"
          :key="tg.path"
          class="flex items-center gap-2 py-1 text-[12px]"
        >
          <span class="w-1.5 h-1.5 rounded-full flex-shrink-0" :style="{ background: tg.color }" />
          <span class="font-mono text-[11px]"
                :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.4)' }">
            {{ tg.path }}
          </span>
          <span :style="{ color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.75)' }">
            {{ tg.label }}
          </span>
        </div>
      </div>
    </div>

    <!-- 总线程数 -->
    <div class="inline-flex items-center gap-1.5">
      <Users :size="13" :color="isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.45)'" />
      <span :style="{ color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.75)' }">
        <template v-if="onlyArrivals">
          <b class="font-semibold">{{ rpsTarget ?? '?' }}</b>
          <span class="ml-1" :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }">RPS</span>
        </template>
        <template v-else>
          <b class="font-semibold">{{ threadsTotal }}</b> VU
        </template>
      </span>
    </div>

    <!-- 总时长 -->
    <div class="inline-flex items-center gap-1.5">
      <Clock :size="13" :color="isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.45)'" />
      <span :style="{ color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.75)' }">
        <b class="font-semibold">{{ formatDuration(durationSec) }}</b>
      </span>
    </div>

    <!-- 环境 -->
    <div class="inline-flex items-center gap-1.5">
      <Globe :size="13" :color="isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.45)'" />
      <template v-if="environment">
        <span :style="{ color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.75)' }">
          <b class="font-semibold">{{ environment.name }}</b>
        </span>
      </template>
      <span v-else :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }">
        无环境
      </span>
    </div>

    <!-- CSV 绑定数 -->
    <div class="inline-flex items-center gap-1.5">
      <FileSpreadsheet :size="13" :color="isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.45)'" />
      <span :style="{ color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.75)' }">
        <b class="font-semibold">{{ csvCount }}</b> CSV
      </span>
    </div>

    <!-- 变化提示：所选历史 run 的快照跟当前 task 不一致时显示 -->
    <div
      v-if="hasChanged"
      class="inline-flex items-center gap-1 ml-auto cursor-help"
      :style="{ color: '#f59e0b' }"
      title="所选历史 run 的脚本或线程组配置已被改动；左侧显示的是该 run 跑时的快照（与当前任务配置不一致）"
    >
      <AlertTriangle :size="12" />
      <span class="text-[11px]">脚本或线程组配置已变化</span>
    </div>
  </div>

  <!-- 没配置 Step 2 时的兜底提示 -->
  <div
    v-else
    :class="embedded ? 'text-[12px]' : 'rounded-xl px-4 py-2.5 text-[12.5px]'"
    :style="embedded
      ? { color: '#f59e0b' }
      : {
          background: isDark ? 'rgba(245,158,11,0.08)' : 'rgba(245,158,11,0.06)',
          border: '1px solid rgba(245,158,11,0.25)',
          color: '#f59e0b',
        }"
  >
    本任务还未完成 Step 2 配置，无法运行。请回到「任务配置」选择场景与参数。
  </div>
</template>
