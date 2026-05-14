<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { ChevronDown, ChevronRight } from 'lucide-vue-next'
import type { TaskRun } from '@/types/task'
import { runsApi } from '@/lib/api'

const props = defineProps<{
  run: TaskRun | null
  isTerminal: boolean
  isDark: boolean
}>()

// 两段折叠态：默认两段都展开
const showPrecheck = ref(true)
const showRuntime = ref(true)

// 预检 + falcon 层运行事件直接从 run 对象拿（外层 ExecuteStage 已 3s 轮询）。
const preCheckLines = computed(() =>
  (props.run?.pre_check_log || '').split('\n').filter(Boolean),
)
const runtimeFalconLines = computed(() =>
  (props.run?.runtime_log || '').split('\n').filter(Boolean),
)

// JMeter 子进程日志：直接拉 /runs/:id/log/?tail=N（运行中本组件自己轮询，终态停）
const jmeterLines = ref<string[]>([])
let pollTimer: ReturnType<typeof setInterval> | null = null

async function pollJmeterLog(): Promise<void> {
  const runId = props.run?.run_id
  if (!runId) return
  try {
    const res = await runsApi.log(runId, 500)
    jmeterLines.value = res.lines.map((l) => l.replace(/\n$/, ''))
  } catch {
    // 静默：log 端点 500 时不打扰用户（subprocess 还没起 / 已归档）
  }
}

function startPolling(): void {
  if (pollTimer) return
  pollJmeterLog()
  pollTimer = setInterval(pollJmeterLog, 3000)
}

function stopPolling(): void {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// 切 run 或终态切换时重新决策轮询
watch(
  () => [props.run?.run_id, props.isTerminal] as const,
  ([runId, terminal]) => {
    stopPolling()
    if (!runId) return
    // 终态时拉一次定格即可；活跃 run 持续轮询
    if (terminal) {
      pollJmeterLog()
    } else {
      startPolling()
    }
  },
  { immediate: true },
)

onUnmounted(stopPolling)

// 行染色：预检 emoji 行；运行事件按 | LEVEL | 段位
function preCheckColor(line: string): string {
  if (line.startsWith('✅')) return '#10b981'
  if (line.startsWith('❌')) return '#ef4444'
  if (line.startsWith('⚠️') || line.startsWith('⚠')) return '#f59e0b'
  if (line.startsWith('ℹ')) return props.isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)'
  if (line.startsWith('[预检]')) return props.isDark ? '#a78bfa' : '#7c3aed'
  return props.isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)'
}

function runtimeColor(line: string): string {
  // 格式：HH:MM:SS.mmm | LEVEL | msg
  if (line.includes('| ERROR')) return '#ef4444'
  if (line.includes('| WARN')) return '#f59e0b'
  if (line.includes('| INFO')) return props.isDark ? 'rgba(255,255,255,0.75)' : 'rgba(0,0,0,0.75)'
  return props.isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.6)'
}

const sectionBg = computed(() =>
  props.isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
)
const sectionBorder = computed(() =>
  props.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
)
const dimColor = computed(() =>
  props.isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)',
)
</script>

<template>
  <div class="h-full overflow-y-auto p-3 flex flex-col gap-3">
    <!-- 段 1：预检 -->
    <div
      class="rounded-xl"
      :style="{ background: sectionBg, border: `1px solid ${sectionBorder}` }"
    >
      <button
        class="w-full flex items-center gap-2 px-4 py-2.5 text-[12.5px] cursor-pointer"
        :style="{ color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.85)' }"
        @click="showPrecheck = !showPrecheck"
      >
        <component :is="showPrecheck ? ChevronDown : ChevronRight" :size="14" />
        <span class="font-medium">预检</span>
        <span class="text-[11px]" :style="{ color: dimColor }">
          {{ preCheckLines.length }} 行
        </span>
      </button>
      <div
        v-if="showPrecheck"
        class="px-4 pb-3 text-[12.5px] leading-[1.7] font-mono"
        :style="{ borderTop: `1px solid ${sectionBorder}` }"
      >
        <div v-if="!preCheckLines.length" class="py-2" :style="{ color: dimColor }">
          还没有预检输出
        </div>
        <div
          v-for="(line, i) in preCheckLines"
          :key="i"
          :style="{ color: preCheckColor(line) }"
        >{{ line }}</div>
      </div>
    </div>

    <!-- 段 2：执行 = falcon 层运行事件 + JMeter 子进程日志 -->
    <div
      class="rounded-xl"
      :style="{ background: sectionBg, border: `1px solid ${sectionBorder}` }"
    >
      <button
        class="w-full flex items-center gap-2 px-4 py-2.5 text-[12.5px] cursor-pointer"
        :style="{ color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.85)' }"
        @click="showRuntime = !showRuntime"
      >
        <component :is="showRuntime ? ChevronDown : ChevronRight" :size="14" />
        <span class="font-medium">执行</span>
        <span class="text-[11px]" :style="{ color: dimColor }">
          {{ runtimeFalconLines.length }} 条事件 · {{ jmeterLines.length }} 行 JMeter log
        </span>
        <span
          v-if="!isTerminal && run"
          class="text-[10px] px-1.5 py-0.5 rounded ml-auto"
          :style="{
            background: isDark ? 'rgba(34,197,94,0.15)' : 'rgba(34,197,94,0.12)',
            color: '#22c55e',
          }"
        >LIVE 3s</span>
      </button>
      <div
        v-if="showRuntime"
        class="px-4 pb-3 text-[12.5px] leading-[1.7] font-mono"
        :style="{ borderTop: `1px solid ${sectionBorder}` }"
      >
        <!-- 子段 2a：falcon 层事件 -->
        <div
          class="text-[10.5px] uppercase tracking-wider pt-2 pb-1"
          :style="{ color: dimColor }"
        >Falcon 调度事件</div>
        <div v-if="!runtimeFalconLines.length" :style="{ color: dimColor }">
          还没有运行事件
        </div>
        <div
          v-for="(line, i) in runtimeFalconLines"
          :key="`f-${i}`"
          :style="{ color: runtimeColor(line) }"
        >{{ line }}</div>

        <!-- 子段 2b：JMeter 子进程 log（末 500 行） -->
        <div
          class="text-[10.5px] uppercase tracking-wider pt-3 pb-1"
          :style="{ color: dimColor }"
        >JMeter 子进程日志（末 500 行）</div>
        <div v-if="!jmeterLines.length" :style="{ color: dimColor }">
          {{ run ? 'JMeter 还没输出日志' : '尚未启动 run' }}
        </div>
        <div
          v-for="(line, i) in jmeterLines"
          :key="`j-${i}`"
          :style="{ color: isDark ? 'rgba(255,255,255,0.62)' : 'rgba(0,0,0,0.65)' }"
        >{{ line }}</div>
      </div>
    </div>
  </div>
</template>
