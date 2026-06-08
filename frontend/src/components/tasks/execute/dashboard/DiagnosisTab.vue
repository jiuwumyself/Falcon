<script setup lang="ts">
// 服务诊断（合并 服务面板+链路面板+JVM）：每个被压测服务一行汇总，手风琴展开看详情。
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Stethoscope } from 'lucide-vue-next'
import DiagnosisServiceRow from './diagnosis/DiagnosisServiceRow.vue'
import type { Task, TaskRun } from '@/types/task'

const props = defineProps<{ task: Task; run: TaskRun | null; isDark: boolean }>()
const d = (l: string, dk: string) => (props.isDark ? dk : l)

const services = computed(() => props.task.service_names || [])
const TERMINAL = ['success', 'failed', 'timeout', 'cancelled', 'pre_check_failed']
const isTerminal = computed(() => !!props.run?.status && TERMINAL.includes(props.run.status))
const hasRun = computed(() => !!props.run?.run_id)

// ── 时间窗选择 ──：本次压测=run 记录的时段（仅有 run 时可选）；其余=截至当前的近 N 分钟
const RANGES = [
  { id: 'run', label: '本次压测', sec: 0 },
  { id: '5m', label: '近 5 分', sec: 300 },
  { id: '15m', label: '近 15 分', sec: 900 },
  { id: '30m', label: '近 30 分', sec: 1800 },
  { id: '1h', label: '近 1 时', sec: 3600 },
  { id: '3h', label: '近 3 时', sec: 10800 },
] as const
const availRanges = computed(() => (hasRun.value ? RANGES : RANGES.filter((r) => r.id !== 'run')))
const range = ref<string>(hasRun.value ? 'run' : '5m')   // 没压测过 → 默认近 5 分
watch(hasRun, (h) => { if (!h && range.value === 'run') range.value = '5m' })
// 切到某个 run（含从历史下拉选历史 run）→ 时间窗回到「本次压测」
watch(() => props.run?.run_id, (rid) => { if (rid) range.value = 'run' })

// 近 N 分时每 10s 让窗口跟着走（仅刷新轻量汇总，不重拉拓扑/详情，见 DiagnosisServiceRow）
const nowTick = ref(Math.floor(Date.now() / 1000))
let timer: ReturnType<typeof setInterval> | null = null
watch(range, (r) => {
  if (timer) { clearInterval(timer); timer = null }
  if (r !== 'run') {
    nowTick.value = Math.floor(Date.now() / 1000)
    timer = setInterval(() => { nowTick.value = Math.floor(Date.now() / 1000) }, 10000)
  }
}, { immediate: true })

const win = computed(() => {
  const r = RANGES.find((x) => x.id === range.value) || RANGES[1]
  if (r.id === 'run') {
    const e = props.run?.finished_at ? Math.floor(new Date(props.run.finished_at).getTime() / 1000) : Math.floor(Date.now() / 1000)
    // started_at 还没写入时退回近 10 分钟，避免从 epoch 0 拉出几十年的空轴
    const s = props.run?.started_at ? Math.floor(new Date(props.run.started_at).getTime() / 1000) : e - 600
    return { start: s, end: e }
  }
  const e = nowTick.value
  return { start: e - r.sec, end: e }
})

// ── CPU 高的排前面 ──：各行汇总加载 CPU 后 emit 上来，按 CPU 降序
const cpuMap = ref<Record<string, number | null>>({})
function onCpu(svc: string, cpu: number | null) { cpuMap.value = { ...cpuMap.value, [svc]: cpu } }
const sortedServices = computed(() =>
  [...services.value].sort((a, b) => (cpuMap.value[b] ?? -1) - (cpuMap.value[a] ?? -1)))

// 手风琴：一次只展一个；默认不展开（没点开就不加载里面的数据）
const expanded = ref('')
watch(services, (s) => { if (!s.includes(expanded.value)) expanded.value = '' }, { immediate: true })
function toggle(svc: string) { expanded.value = expanded.value === svc ? '' : svc }
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <div class="h-full min-h-0 overflow-y-auto">
    <div class="p-4 space-y-2.5">
      <p v-if="!services.length" class="text-[12px] py-10 text-center"
         :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">
        <Stethoscope :size="20" class="inline-block mb-2" /><br>请在 Step 2 选择服务以查看诊断面板。
      </p>
      <template v-else>
        <!-- 时间窗：本次压测 + 下拉选近 N 分（右对齐）-->
        <div class="flex items-center justify-end gap-2 px-0.5">
          <span class="text-[10px]" :style="{ color: d('rgba(0,0,0,0.35)', 'rgba(255,255,255,0.35)') }">时间窗</span>
          <select v-model="range"
                  class="text-[12px] px-2 py-1 rounded-md outline-none cursor-pointer"
                  :style="{
                    background: d('rgba(0,0,0,0.04)', 'rgba(255,255,255,0.06)'),
                    color: d('#1a1a2e', '#fff'),
                    border: `1px solid ${d('rgba(0,0,0,0.08)', 'rgba(255,255,255,0.1)')}`,
                  }">
            <option v-for="r in availRanges" :key="r.id" :value="r.id"
                    :style="{ background: d('#fff', '#1a2330'), color: d('#1a1a2e', '#fff') }">{{ r.label }}</option>
          </select>
        </div>
        <DiagnosisServiceRow
          v-for="svc in sortedServices" :key="svc"
          :task="task" :run="run" :service="svc"
          :expanded="expanded === svc" :is-terminal="isTerminal"
          :start-sec="win.start" :end-sec="win.end" :range="range" :is-dark="isDark"
          @toggle="toggle(svc)" @cpu="onCpu"
        />
      </template>
    </div>
  </div>
</template>
