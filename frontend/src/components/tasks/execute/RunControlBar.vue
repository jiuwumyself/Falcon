<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Play, Square, Loader } from 'lucide-vue-next'
import type { RunEvent, RunEventType, RunStatus, Task, TaskRun } from '@/types/task'
import { plannedDurationSec } from '@/lib/planSummary'
import { STATUS_META } from './runStatusMeta'

const props = defineProps<{
  selectedRun: TaskRun | null
  events: RunEvent[]
  task: Task                   // 进度条阶段估算用
  durationSeconds: number      // task.duration_seconds，回退兜底
  busy: boolean
  startDisabled?: boolean      // config_stale 时上层 disable 开始按钮；兜底默认 false
  hideControls?: boolean       // 分享视图：只读，藏开始/停止按钮，仅留状态徽章 + 进度条 + 时间
  isDark: boolean
}>()

const emit = defineEmits<{
  (e: 'start'): void
  (e: 'stop'): void
}>()

const ACTIVE: RunStatus[] = ['pre_checking', 'pending', 'running', 'cancelling']
const isActive = computed(() => !!props.selectedRun && ACTIVE.includes(props.selectedRun.status))
// cancelling 状态：按钮 disabled + 文字变「取消中…」，避免重复点击触发多次 cancel
const isCancelling = computed(() => props.selectedRun?.status === 'cancelling')
// 终态判断：用 status 是否不在 ACTIVE 里决定，不依赖 startedMs/finishedMs。
// 修复：pre_checking/pending 阶段被强杀时 started_at=null，若依赖 startedMs 判断会失效。
const isTerminalStatus = computed(() =>
  !!props.selectedRun && !ACTIVE.includes(props.selectedRun.status),
)

// ─── 时间基准 ────────────────────────────────────────────
// 进度条起点 = run.created_at（pre_check 开始）
// 进度条满 = max_wall_sec + pre_check 实测耗时（覆盖 run 全程）
const now = ref(Date.now())
let tickTimer: number | undefined
onMounted(() => {
  tickTimer = window.setInterval(() => { now.value = Date.now() }, 1000)
})
onBeforeUnmount(() => {
  if (tickTimer) clearInterval(tickTimer)
})

const startedMs = computed<number | null>(() => {
  const r = props.selectedRun
  return r?.started_at ? new Date(r.started_at).getTime() : null
})
const finishedMs = computed<number | null>(() => {
  const r = props.selectedRun
  return r?.finished_at ? new Date(r.finished_at).getTime() : null
})
// 进度条起点：优先 created_at（pre_check 起点）；老 run 无该字段时回退 started_at
const createdMs = computed<number | null>(() => {
  const r = props.selectedRun
  if (r?.created_at) return new Date(r.created_at).getTime()
  return startedMs.value
})

// pre_check 实测秒数（created_at → started_at）；老 run / created_at 缺失时 = 0
const preCheckSec = computed<number>(() => {
  const r = props.selectedRun
  if (!r?.created_at || !startedMs.value) return 0
  const created = new Date(r.created_at).getTime()
  return Math.max(0, Math.round((startedMs.value - created) / 1000))
})

// 预检估算时长 + 视觉占位：pre_check 真实时间相对整 run 太短（1-3s / 600s ≈ 0.5%
// 看不清），所以单独给它一个时间→宽度映射：在 PRE_CHECK_ESTIMATE_SEC 内线性长到
// PRE_CHECK_VISIBLE_MAX_PCT，不让 totalSec 跟着切来切去（避免运行起来 bar 大缩）。
const PRE_CHECK_ESTIMATE_SEC = 8
const PRE_CHECK_VISIBLE_MAX_PCT = 4

// 进度条总秒数 = pre_check + 计划时长。
// 空盘（无 selectedRun）时返 0 → totalStr 显示 00:00。
// 终态且有 started_at + finished_at：用实际 elapsed 定格，bar 100% 满填。
// 终态但 started_at=null（pre_check/pending 被强杀）：用计划时长兜底，
//   elapsedSec 已由 finishedMs 定格，不会继续滚动。
// 非终态（pre_checking / pending / running / cancelling）：preCheck + plannedDurationSec
//   —— 跟任务卡上显示的"X 分 X 秒"对齐；不用 r.max_wall_sec（那个含 shutdown 给
//   executor 超时检测用，对 ConcurrencyThreadGroup 会多算 shutdown 秒数）。
const totalSec = computed<number>(() => {
  if (!props.selectedRun) return 0
  if (isTerminalStatus.value && finishedMs.value && startedMs.value) {
    return Math.max(1, elapsedSec.value)
  }
  const cfgPlan = plannedDurationSec(props.task.thread_groups_config)
  const wall = cfgPlan || props.durationSeconds || 0
  const total = preCheckSec.value + wall
  return Math.max(1, total)
})

// 当前 elapsed（相对 created_at）：
// - 终态：强制用 finished_at 定格（started_at=null 时也能定格，不再滚动）
//   修复：pre_checking/pending 阶段被强杀时 started_at=null，原逻辑
//   finishedMs ?? now 在非终态路径下仍走 now.value，计时器持续滚动。
// - 非终态：实时用 now.value 滚动
const elapsedSec = computed<number>(() => {
  if (!createdMs.value) return 0
  if (isTerminalStatus.value) {
    const end = finishedMs.value ?? now.value
    return Math.max(0, Math.floor((end - createdMs.value) / 1000))
  }
  return Math.max(0, Math.floor((now.value - createdMs.value) / 1000))
})

function fmtTime(s: number): string {
  const m = Math.floor(s / 60), sec = s % 60
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}
const elapsedStr = computed(() => fmtTime(elapsedSec.value))
const totalStr = computed(() => fmtTime(totalSec.value))

// 时间 → 视觉位置映射：pre_check 永远占 [0, PRE_CHECK_VISIBLE_MAX_PCT]，
// run 段（含 ramp/steady/cool_down）占 [PRE_CHECK_VISIBLE_MAX_PCT, 100]。
// 这样 pre_check 在 RUNNING 后也能被看见（4% 宽），同时 run 期其他段比例自洽。
// 输入 sec = 距 created_at 的秒数；输出 [0, 100] 视觉百分比。
function secToVisualPct(sec: number): number {
  if (sec < 0) return 0
  if (!startedMs.value) {
    // pre_check 期（or 在 pre_check 阶段终态）：按 PRE_CHECK_ESTIMATE_SEC 线性长，
    // 上限 PRE_CHECK_VISIBLE_MAX_PCT 不抢整条。
    const grown = (sec / PRE_CHECK_ESTIMATE_SEC) * PRE_CHECK_VISIBLE_MAX_PCT
    return Math.min(PRE_CHECK_VISIBLE_MAX_PCT, grown)
  }
  const pcReal = preCheckSec.value
  const wall = Math.max(0, totalSec.value - pcReal)
  if (sec <= pcReal) {
    if (pcReal <= 0) return 0
    return (sec / pcReal) * PRE_CHECK_VISIBLE_MAX_PCT
  }
  if (wall <= 0) return 100
  const runSec = sec - pcReal
  return Math.min(100, PRE_CHECK_VISIBLE_MAX_PCT + (runSec / wall) * (100 - PRE_CHECK_VISIBLE_MAX_PCT))
}

const progressPct = computed(() => {
  if (!totalSec.value) return 0
  return secToVisualPct(elapsedSec.value)
})

// ─── 5 段 phase 边界（百分比，相对 totalSec）────────────────
// pre_check_end_pct: pre_check 结束位置 = preCheckSec / totalSec
// startup_wait_end_pct: first_sample 时刻 / totalSec
// ramp_end_pct: ramp_done 时刻 / totalSec
// steady_end_pct: shutdown_start 时刻 / totalSec
// 100%: finished_at 或 totalSec

function eventTsToPct(eventType: RunEventType): number | null {
  if (!createdMs.value) return null
  const e = props.events.find((x) => x.event_type === eventType)
  if (!e) return null
  const sec = (e.ts_ms - createdMs.value) / 1000
  return secToVisualPct(sec)
}

const preCheckEndPct = computed(() => {
  if (!createdMs.value) return 0
  // pre_check 期：pcEnd 跟 progressPct 一起长（progressPct 已经被 secToVisualPct 限到 4%）
  if (!startedMs.value) {
    return progressPct.value
  }
  // RUNNING+ / 终态：pre_check 一律占 PRE_CHECK_VISIBLE_MAX_PCT，让它在 bar 上始终可见
  return PRE_CHECK_VISIBLE_MAX_PCT
})
const firstSamplePct = computed(() => eventTsToPct('first_sample'))
const rampDonePct = computed(() => eventTsToPct('ramp_done'))
const shutdownStartPct = computed(() => eventTsToPct('shutdown_start'))

// 5 段的端点（每段 [start, end] %）。运行中事件可能还没写入 → fallback 用 task 配置算估计位置。
// 空盘（无 selectedRun）时返 [] → 模板 v-for 不渲染任何染色段，进度条只剩灰底。
const phaseSegments = computed(() => {
  if (!props.selectedRun) return []
  const ramp = props.selectedRun?.ramp_up_seconds || 0
  const dur = props.selectedRun?.duration_seconds || 0

  // pre_check 段
  const pcEnd = preCheckEndPct.value

  // startup_wait 段：started_at → first_sample；fallback 取 started_at + 2s 默认估计
  let swEnd = firstSamplePct.value
  if (swEnd === null) {
    swEnd = secToVisualPct(preCheckSec.value + 2)
  }
  swEnd = Math.max(swEnd, pcEnd)

  // ramp 段：first_sample → ramp_done；fallback = started_at + ramp_up_seconds
  let rampEnd = rampDonePct.value
  if (rampEnd === null) {
    rampEnd = secToVisualPct(preCheckSec.value + ramp)
  }
  rampEnd = Math.max(rampEnd, swEnd)

  // steady 段：ramp_done → shutdown_start；fallback = ramp_end + duration_seconds
  let steadyEnd = shutdownStartPct.value
  if (steadyEnd === null) {
    steadyEnd = secToVisualPct(preCheckSec.value + ramp + dur)
  }
  steadyEnd = Math.max(steadyEnd, rampEnd)

  return [
    { name: 'pre_check', start: 0, end: pcEnd, color: '#9ca3af', label: '预检', desc: '启动前的 6 项检查（JMeter / JMX / 磁盘 / InfluxDB / Hosts / 压力源）' },
    { name: 'startup_wait', start: pcEnd, end: swEnd, color: '#60a5fa', label: '启动等待', desc: 'JMeter 已起，等首条 sample 出现' },
    { name: 'ramp_up', start: swEnd, end: rampEnd, color: '#3b82f6', label: 'ramp 加压', desc: '逐步增加并发 VU 到目标' },
    { name: 'steady', start: rampEnd, end: steadyEnd, color: '#10b981', label: 'steady 稳态', desc: '稳定并发期，主要数据来自这段' },
    { name: 'cool_down', start: steadyEnd, end: 100, color: '#a78bfa', label: '收尾 cool_down', desc: 'shutdown 信号后等 VU 自然退出' },
  ]
})

// 进度填充：每段填充宽度 = min(progressPct, segment.end) - segment.start
// secToVisualPct 保证 progressPct 和 pcEnd 在 !startedMs 期同步，RUNNING 后 progressPct
// 自然 ≥ pcEnd（pre_check 段总能填满）—— 不再需要 pre_check 特殊 override。
function fillWidth(segStart: number, segEnd: number): number {
  return Math.max(0, Math.min(progressPct.value, segEnd) - segStart)
}

// ─── 状态徽章 ───（STATUS_META 已抽到 runStatusMeta.ts 共享）
const statusInfo = computed(() => {
  if (!props.selectedRun) return { label: '待执行', color: '#9ca3af' }
  return STATUS_META[props.selectedRun.status] || { label: props.selectedRun.status, color: '#6b7280' }
})
const statusTooltip = computed(() => {
  const r = props.selectedRun
  if (!r) return '尚未启动 run'
  const parts = [`状态：${statusInfo.value.label}`]
  if (preCheckSec.value > 0) parts.push(`预检：${preCheckSec.value}s`)
  if (r.started_at) parts.push(`开始：${new Date(r.started_at).toLocaleTimeString()}`)
  if (r.finished_at) parts.push(`结束：${new Date(r.finished_at).toLocaleTimeString()}`)
  // 原生 title 不支持 \n 换行，用 · 分隔
  return parts.join(' · ')
})

// ─── 突发/告警事件色块（窄竖条）─────────────────────────────
// phase 边界（ramp_done / hold_start / shutdown_start / first_sample）不画——已经被染色边界表达
const EVENT_META: Record<RunEventType, { label: string; color: string; desc: string } | null> = {
  ramp_done: null,
  hold_start: null,
  shutdown_start: null,
  first_sample: null,
  first_error: { label: '首次错误', color: '#f59e0b', desc: '第一次出现失败的 sample' },
  first_5xx: { label: '首次 5xx', color: '#fb923c', desc: '第一次出现服务端 5xx 错误' },
  error_rate_breached: { label: '错误率告警', color: '#ef4444', desc: '错误率破 80% 阈值，触发 early abort' },
  p99_sla_breached: { label: 'P99 破 SLA', color: '#dc2626', desc: 'P99 延迟超出 task SLA' },
  throughput_plateau: { label: '吞吐拐点', color: '#a855f7', desc: '加 VU 但 RPS 不再线性增长' },
}

// ─── 进度条 hover 浮窗（跨鼠标 X 联动，fixed 定位逃出卡片堆叠）─────
// 用 viewport 坐标（clientX/clientY）+ Teleport 到 body，避免被上方错误条遮挡
// 端点自适应 translateX：靠左用 0 / 靠右用 -100% / 中间用 -50%，避免文字飞出 viewport
// 命中优先级：事件细条（距离 < 4px）> phase 段
const hoverInfo = ref<{ clientX: number; topY: number; title: string; desc: string } | null>(null)

function onProgressMouseMove(e: MouseEvent) {
  if (!phaseSegments.value.length || !totalSec.value) {
    hoverInfo.value = null
    return
  }
  const el = e.currentTarget as HTMLElement
  const rect = el.getBoundingClientRect()
  const x = e.clientX - rect.left

  // 1) 优先：是否落在事件细条上（4px 命中范围，给 3px 色条留 0.5px padding）
  const eventHit = eventMarkers.value.find((m) => {
    const evtX = (m.leftPct / 100) * rect.width
    return Math.abs(x - evtX) < 4
  })
  if (eventHit) {
    hoverInfo.value = {
      clientX: e.clientX,
      topY: rect.top,
      title: eventHit.meta.label,
      desc: eventHit.meta.desc,
    }
    return
  }

  // 2) 否则按 phase 段
  const pct = Math.max(0, Math.min(100, (x / rect.width) * 100))
  const seg = phaseSegments.value.find((s) => pct >= s.start && pct < s.end)
    ?? phaseSegments.value[phaseSegments.value.length - 1]
  if (!seg) { hoverInfo.value = null; return }
  hoverInfo.value = {
    clientX: e.clientX,
    topY: rect.top,
    title: seg.label,
    desc: seg.desc,
  }
}

function onProgressMouseLeave() {
  hoverInfo.value = null
}

// 浮窗端点自适应 translateX：避免左/右贴边时文字飞出 viewport
const hoverTransform = computed(() => {
  if (!hoverInfo.value) return 'translateX(-50%)'
  const x = hoverInfo.value.clientX
  const w = typeof window !== 'undefined' ? window.innerWidth : 1920
  if (x < 80) return 'translateX(0)'             // 靠左：浮窗左对齐鼠标
  if (x > w - 80) return 'translateX(-100%)'     // 靠右：浮窗右对齐鼠标
  return 'translateX(-50%)'                       // 中间：浮窗居中
})

type EventMeta = { label: string; color: string; desc: string }
const eventMarkers = computed(() => {
  if (!createdMs.value) return []
  return props.events
    .map((e) => {
      const meta = EVENT_META[e.event_type]
      if (!meta) return null
      const sec = (e.ts_ms - createdMs.value!) / 1000
      const leftPct = secToVisualPct(sec)
      return { meta, leftPct }
    })
    .filter((x): x is { meta: EventMeta; leftPct: number } => x !== null)
})

</script>

<template>
  <div
    class="flex flex-col gap-2 px-3 py-2.5 rounded-xl"
    :style="{
      background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)',
      border: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
    }"
  >
  <!-- 第一行：状态徽章 + 进度条 + 时间 + 按钮 + 历史 -->
  <div class="flex items-center gap-3">
    <!-- 状态徽章：active 时 spinner，终态 / 空盘用静态圆点 -->
    <span
      class="flex items-center gap-1.5 px-2 py-1 rounded text-[11px] flex-shrink-0 cursor-help whitespace-pre-line"
      :style="{
        background: `${statusInfo.color}1f`,
        color: statusInfo.color,
      }"
      :title="statusTooltip"
    >
      <Loader v-if="isActive" :size="11" class="animate-spin" />
      <span v-else
            class="w-1.5 h-1.5 rounded-full"
            :style="{ background: statusInfo.color }" />
      {{ statusInfo.label }}
    </span>

    <!-- 进度条（5 段染色 + 嵌入式事件色块 + 跨鼠标 hover 浮窗）；占满中间，时间在右侧 -->
    <!-- 容器 18px 高：12px 主条 + 上下各 3px 余量 -->
    <div
      class="relative flex-1 min-w-0"
      :style="{ height: '18px' }"
      @mousemove="onProgressMouseMove"
      @mouseleave="onProgressMouseLeave"
    >
      <!-- 灰底底条（12px 高） -->
      <div
        class="absolute left-0 right-0 top-1/2 -translate-y-1/2 rounded-full overflow-hidden"
        :style="{
          height: '12px',
          background: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)',
        }"
      >
        <!-- 5 段染色填充（空盘时 phaseSegments=[] → 不渲染） -->
        <div
          v-for="seg in phaseSegments"
          :key="seg.name"
          class="absolute top-0 h-full transition-all duration-300"
          :style="{
            left: `${seg.start}%`,
            width: `${fillWidth(seg.start, seg.end)}%`,
            background: seg.color,
            opacity: isActive ? 1 : 0.85,
          }"
        />
        <!-- 嵌入式事件色块（3×12px，无边框无外发光，纯一道色条嵌进 phase 段里） -->
        <div
          v-for="(m, i) in eventMarkers"
          :key="`evt-${i}`"
          class="absolute top-1/2"
          :style="{
            left: `${m.leftPct}%`,
            width: '3px',
            height: '12px',
            transform: 'translate(-50%, -50%)',
            background: m.meta.color,
            zIndex: 2,
          }"
        />
      </div>

    </div>

    <!-- 时间：进度条右侧、按钮之前；空盘时显示 00:00 / 00:00 -->
    <span
      class="text-[11px] tabular-nums flex-shrink-0"
      :style="{ color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)' }"
    >
      {{ elapsedStr }}
      <span :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">
        / {{ totalStr }}
      </span>
    </span>

    <!-- 按钮组：开始/停止（分享视图隐藏）-->
    <div v-if="!hideControls" class="flex items-center gap-1.5 flex-shrink-0">
      <button
        v-if="!isActive"
        class="flex items-center gap-1 px-3 py-1.5 rounded-lg text-[12px] cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
        :style="{ background: '#10b981', color: '#fff' }"
        :disabled="busy || startDisabled"
        :title="startDisabled ? '线程组配置已过期，请回 Step 2 重新保存' : ''"
        @click="emit('start')"
      >
        <Loader v-if="busy" :size="12" class="animate-spin" />
        <Play v-else :size="12" />
        {{ selectedRun ? '重新开始' : '开始' }}
      </button>
      <button
        v-else
        class="flex items-center gap-1 px-3 py-1.5 rounded-lg text-[12px] cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
        :style="{ background: '#ef4444', color: '#fff' }"
        :disabled="busy || isCancelling"
        @click="emit('stop')"
      >
        <Loader v-if="busy || isCancelling" :size="12" class="animate-spin" />
        <Square v-else :size="12" />
        {{ isCancelling ? '取消中…' : '停止' }}
      </button>
      <!-- 历史下拉已迁到 RunDashboard 标签行（见 RunHistoryDropdown.vue）-->
    </div>
  </div>

  <!-- 任务简介条已挪到 RunDashboard 标签行末尾（见 RunDashboard.vue）-->
  </div>

  <!-- Hover 浮窗：Teleport 到 body 用 fixed 定位逃出卡片堆叠 -->
  <!-- 内容 = 段名 · 一句解释；事件命中（距离 < 4px）时是事件解释，否则是 phase 解释 -->
  <Teleport to="body">
    <div
      v-if="hoverInfo"
      class="fixed pointer-events-none text-[10.5px] whitespace-nowrap px-2 py-0.5 rounded shadow-lg"
      :style="{
        left: `${hoverInfo.clientX}px`,
        top: `${hoverInfo.topY - 28}px`,
        transform: hoverTransform,
        background: isDark ? 'rgba(20,20,24,0.96)' : 'rgba(255,255,255,0.96)',
        color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.85)',
        border: `1px solid ${isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)'}`,
        zIndex: 1000,
      }"
    >
      <span class="font-medium">{{ hoverInfo.title }}</span>
      <span :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.5)' }">
        · {{ hoverInfo.desc }}
      </span>
    </div>
  </Teleport>
</template>
