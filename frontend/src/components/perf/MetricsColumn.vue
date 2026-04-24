<script setup lang="ts">
import { computed, ref } from 'vue'
import { AnimatePresence, Motion } from 'motion-v'
import {
  Activity, AlertTriangle, Clock, Gauge, Timer, Users,
} from 'lucide-vue-next'
import {
  P99_THRESHOLD, parseDuration, parseTime, PEOPLE, SPRING, stColor, type Task,
} from './data'
import Anim from './Anim.vue'
import WaveSpark from './WaveSpark.vue'

const props = defineProps<{
  isDark: boolean
  tasks: Task[]
  focusedTask: string | null
  rimColor: string
  selectedDate: number
}>()

const emit = defineEmits<{ (e: 'selectDate', d: number): void }>()

const SCHEDULE_HOURS = [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
const ROW_H = 80
const gridStart = SCHEDULE_HOURS[0]
const gridEnd = SCHEDULE_HOURS[SCHEDULE_HOURS.length - 1] + 1
const totalGrid = gridEnd - gridStart
const GRID_HEIGHT = SCHEDULE_HOURS.length * ROW_H

const expandedTask = ref<string | null>(null)

const availableDates = computed(() =>
  [...new Set(props.tasks.map((t) => t.date))].sort((a, b) => b - a),
)
const dayTasks = computed(() => props.tasks.filter((t) => t.date === props.selectedDate))
const totalDayMins = computed(() =>
  dayTasks.value.reduce((s, t) => s + parseDuration(t.duration), 0),
)

const taskLanes = computed(() => {
  const sorted = [...dayTasks.value].sort((a, b) => parseTime(a.time) - parseTime(b.time))
  const lanes: { endPx: number }[] = []
  const assignments: { id: string; lane: number }[] = []
  for (const t of sorted) {
    const startH = parseTime(t.time)
    const durH = parseDuration(t.duration) / 60
    const topPx = ((startH - gridStart) / totalGrid) * GRID_HEIGHT
    const heightPx = Math.max(56, (durH / totalGrid) * GRID_HEIGHT)
    const bottomPx = topPx + heightPx
    let assigned = -1
    for (let l = 0; l < lanes.length; l++) {
      if (lanes[l].endPx <= topPx + 2) { assigned = l; break }
    }
    if (assigned === -1) { assigned = lanes.length; lanes.push({ endPx: bottomPx }) }
    else lanes[assigned].endPx = bottomPx
    assignments.push({ id: t.id, lane: assigned })
  }
  const totalLanes = Math.max(lanes.length, 1)
  const map: Record<string, { lane: number; totalLanes: number }> = {}
  for (const a of assignments) map[a.id] = { lane: a.lane, totalLanes }
  return map
})

const nowIndicator = computed(() => {
  const now = new Date()
  const nowH = now.getHours() + now.getMinutes() / 60
  if (nowH >= gridStart && nowH <= gridEnd && props.selectedDate === now.getDate()) {
    return ((nowH - gridStart) / (gridEnd - gridStart)) * GRID_HEIGHT
  }
  return null
})

function taskBlock(t: Task) {
  const startH = parseTime(t.time)
  const durMins = parseDuration(t.duration)
  const durH = durMins / 60
  const top = ((startH - gridStart) / totalGrid) * GRID_HEIGHT
  const height = Math.max(56, (durH / totalGrid) * GRID_HEIGHT)
  const lane = taskLanes.value[t.id] || { lane: 0, totalLanes: 1 }
  const laneWidth = 100 / lane.totalLanes
  const laneLeft = lane.lane * laneWidth
  const total = t.phases.prep + t.phases.exec + t.phases.analysis
  return {
    top,
    height,
    laneLeft,
    laneWidth,
    lanePad: lane.totalLanes > 1 ? 4 : 0,
    durMins,
    prepPct: (t.phases.prep / total) * 100,
    execPct: (t.phases.exec / total) * 100,
    analysisPct: (t.phases.analysis / total) * 100,
  }
}

const PHASE_LEGEND = [
  { label: 'Prep', color: '#60a5fa' },
  { label: 'Exec', color: '#818cf8' },
  { label: 'Analysis', color: '#a78bfa' },
]

function personByName(name: string) {
  return PEOPLE.find((p) => p.name === name)
}
</script>

<template>
  <div class="flex flex-col h-full py-5 px-4 flex-1 min-w-0">
    <!-- Header -->
    <div class="flex items-center justify-between mb-3 px-1">
      <p
        class="text-[11px] uppercase tracking-[0.2em]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.2)' }"
      >Schedule Planner</p>
      <div class="flex items-center gap-1.5">
        <div v-for="l in PHASE_LEGEND" :key="l.label" class="flex items-center gap-1 ml-2">
          <div class="w-[6px] h-[6px] rounded-sm" :style="{ background: l.color }" />
          <span
            class="text-[10px]"
            :style="{ color: isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.25)' }"
          >{{ l.label }}</span>
        </div>
      </div>
    </div>

    <!-- Date pills -->
    <div class="flex items-center gap-2 mb-3 px-1 overflow-x-auto flex-shrink-0">
      <Motion
        v-for="d in availableDates"
        :key="d"
        as="button"
        :while-tap="{ scale: 0.92 }"
        class="flex items-center gap-2 px-3.5 py-2 rounded-xl cursor-pointer flex-shrink-0 relative overflow-hidden"
        :style="{
          background: d === selectedDate
            ? isDark ? 'rgba(59,130,246,0.12)' : 'rgba(59,130,246,0.08)'
            : isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)',
          border: `1px solid ${d === selectedDate ? 'rgba(59,130,246,0.2)' : isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.04)'}`,
        }"
        @click="emit('selectDate', d)"
      >
        <span
          class="text-[16px] relative z-10"
          :style="{ color: d === selectedDate ? '#3b82f6' : isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
        >{{ d }}</span>
        <span
          class="text-[10px] relative z-10"
          :style="{ color: d === selectedDate ? '#3b82f6' : isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.2)' }"
        >四月</span>
        <span
          class="text-[10px] px-1.5 py-0.5 rounded-md relative z-10"
          :style="{
            background: d === selectedDate
              ? 'rgba(59,130,246,0.1)'
              : isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)',
            color: d === selectedDate ? '#3b82f6' : isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.2)',
          }"
        >{{ tasks.filter((t) => t.date === d).length }}</span>
      </Motion>
    </div>

    <!-- Day summary -->
    <div class="flex items-center gap-4 mb-3 px-2">
      <div class="flex items-center gap-1.5">
        <Activity :size="14" :color="isDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.3)'" />
        <span
          class="text-[12px]"
          :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
        >
          <Anim :value="dayTasks.length" /> 个任务
        </span>
      </div>
      <div class="flex items-center gap-1.5">
        <Clock :size="14" :color="isDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.3)'" />
        <span
          class="text-[12px]"
          :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
        >
          共 <Anim :value="Math.round(totalDayMins)" /> 分钟
        </span>
      </div>
    </div>

    <!-- Time grid -->
    <div class="flex-1 overflow-y-auto pr-1 relative">
      <div class="relative" :style="{ minHeight: `${GRID_HEIGHT}px` }">
        <!-- Hour grid lines -->
        <div
          v-for="(h, i) in SCHEDULE_HOURS"
          :key="h"
          class="absolute left-0 right-0 flex items-start"
          :style="{ top: `${i * ROW_H}px` }"
        >
          <div class="w-[48px] flex-shrink-0 text-right pr-2 -mt-[6px]">
            <span
              class="text-[12px]"
              :style="{ color: isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)' }"
            >{{ String(h).padStart(2, '0') }}:00</span>
          </div>
          <div
            class="flex-1 h-[1px]"
            :style="{ background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.04)' }"
          />
        </div>

        <!-- Now indicator -->
        <div
          v-if="nowIndicator !== null"
          class="absolute left-[48px] right-0 flex items-center z-30 pointer-events-none"
          :style="{ top: `${nowIndicator}px` }"
        >
          <div
            class="w-[8px] h-[8px] rounded-full"
            style="background: #f43f5e; box-shadow: 0 0 8px rgba(244,63,94,0.4)"
          />
          <div
            class="flex-1 h-[1.5px]"
            style="background: linear-gradient(90deg, #f43f5e, transparent)"
          />
        </div>

        <!-- Task blocks -->
        <template v-for="(t, i) in dayTasks" :key="t.id">
          <Motion
            :initial="{ opacity: 0, x: 20, scaleY: 0.8 }"
            :animate="{ opacity: 1, x: 0, scaleY: 1 }"
            :transition="{ delay: i * 0.08, type: 'spring', ...SPRING }"
            class="absolute rounded-2xl overflow-hidden cursor-pointer group"
            :style="{
              top: `${taskBlock(t).top}px`,
              left: `calc(54px + (100% - 58px) * ${taskBlock(t).laneLeft / 100})`,
              width: `calc((100% - 58px) * ${taskBlock(t).laneWidth / 100} - ${taskBlock(t).lanePad}px)`,
              minHeight: '56px',
              height: expandedTask === t.id ? 'auto' : `${taskBlock(t).height}px`,
              zIndex: focusedTask === t.id ? 20 : expandedTask === t.id ? 15 : 10 - i,
              background: isDark ? 'rgba(255,255,255,0.025)' : 'rgba(255,255,255,0.5)',
              border: `1px solid ${focusedTask === t.id ? `${stColor(t.status)}30` : isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.05)'}`,
              boxShadow: focusedTask === t.id
                ? `0 4px 24px ${stColor(t.status)}25, 0 0 0 1px ${stColor(t.status)}20, 0 0 40px ${stColor(t.status)}15`
                : `0 2px 8px rgba(0,0,0,${isDark ? 0.12 : 0.04})`,
              transition: 'all 0.3s ease',
              transform: focusedTask === t.id ? 'scale(1.02)' : undefined,
            }"
            @click="expandedTask = expandedTask === t.id ? null : t.id"
          >
            <div
              class="absolute left-0 top-0 bottom-0 w-[4px] rounded-l-2xl"
              :style="{ background: `linear-gradient(180deg, ${stColor(t.status)}, ${stColor(t.status)}60)` }"
            />
            <div
              class="absolute top-0 left-3 right-3 h-[1px]"
              :style="{ background: `linear-gradient(90deg, transparent, ${rimColor}15, transparent)` }"
            />

            <div class="pl-4 pr-3 py-2.5 relative">
              <div class="absolute -top-[2px] right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                <span
                  class="text-[9px] px-1.5 py-0.5 rounded"
                  :style="{
                    background: isDark ? 'rgba(0,0,0,0.6)' : 'rgba(0,0,0,0.06)',
                    color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.35)',
                  }"
                >{{ taskBlock(t).durMins.toFixed(0) }}min</span>
              </div>

              <div class="flex items-center justify-between mb-2">
                <div class="flex items-center gap-2 min-w-0">
                  <span class="text-[12px] flex-shrink-0" :style="{ color: stColor(t.status) }">{{ t.time }}</span>
                  <Motion
                    v-if="t.status === 'running'"
                    class="w-[6px] h-[6px] rounded-full flex-shrink-0"
                    :style="{ background: stColor(t.status) }"
                    :animate="{ scale: [1, 1.4, 1], opacity: [1, 0.4, 1] }"
                    :transition="{ duration: 1.5, repeat: Infinity }"
                  />
                  <p
                    class="text-[13px] truncate"
                    :style="{ color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)' }"
                  >{{ t.title }}</p>
                </div>
                <span
                  class="text-[11px] px-2 py-0.5 rounded-lg flex-shrink-0 ml-2"
                  :style="{ background: `${stColor(t.status)}0c`, color: stColor(t.status) }"
                >{{ t.duration }}</span>
              </div>

              <!-- Phase bar -->
              <div
                class="relative h-[18px] rounded-md overflow-hidden mb-2"
                :style="{ background: isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)' }"
              >
                <div class="absolute inset-0 flex">
                  <Motion
                    :initial="{ width: 0 }"
                    :animate="{ width: `${taskBlock(t).prepPct}%` }"
                    :transition="{ duration: 0.7, delay: i * 0.06, ease: 'easeOut' }"
                    class="h-full"
                    style="background: linear-gradient(90deg, #3b82f6, #60a5fa)"
                  />
                  <Motion
                    :initial="{ width: 0 }"
                    :animate="{ width: `${taskBlock(t).execPct}%` }"
                    :transition="{ duration: 0.9, delay: i * 0.06 + 0.15, ease: 'easeOut' }"
                    class="h-full"
                    style="background: linear-gradient(90deg, #6366f1, #818cf8)"
                  />
                  <Motion
                    :initial="{ width: 0 }"
                    :animate="{ width: `${taskBlock(t).analysisPct}%` }"
                    :transition="{ duration: 0.6, delay: i * 0.06 + 0.3, ease: 'easeOut' }"
                    class="h-full"
                    style="background: linear-gradient(90deg, #8b5cf6, #a78bfa)"
                  />
                </div>
                <div
                  class="absolute inset-0 pointer-events-none"
                  style="background: linear-gradient(180deg, rgba(255,255,255,0.12), transparent 50%)"
                />
              </div>

              <!-- Owner + metrics -->
              <div class="flex items-center gap-2.5">
                <div
                  v-if="personByName(t.owner)"
                  class="w-5 h-5 rounded-md flex items-center justify-center text-[8px] text-white flex-shrink-0"
                  :style="{
                    background: personByName(t.owner)!.color,
                    boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.15)',
                  }"
                >{{ personByName(t.owner)!.avatar }}</div>
                <span
                  class="text-[11px]"
                  :style="{ color: isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.25)' }"
                >{{ t.owner }}</span>
                <div class="flex items-center gap-3 ml-auto">
                  <span class="text-[10px]" style="color: #60a5fa">
                    <Anim :value="t.rps" /> rps
                  </span>
                  <span
                    class="text-[10px]"
                    :style="{ color: t.p99 > P99_THRESHOLD ? '#f97316' : '#10b981' }"
                  >
                    P99: <Anim :value="t.p99" :decimals="1" suffix="ms" />
                  </span>
                </div>
              </div>

              <!-- Expanded detail -->
              <AnimatePresence>
                <Motion
                  v-if="expandedTask === t.id"
                  :initial="{ height: 0, opacity: 0 }"
                  :animate="{ height: 'auto', opacity: 1 }"
                  :exit="{ height: 0, opacity: 0 }"
                  :transition="{ type: 'spring', ...SPRING }"
                  class="overflow-hidden"
                >
                  <div
                    class="my-2.5 h-[1px]"
                    :style="{ background: `linear-gradient(90deg, transparent, ${rimColor}10, transparent)` }"
                  />
                  <div class="flex gap-2.5 mb-2.5">
                    <div
                      v-for="ph in [
                        { label: '脚本准备', val: `${t.phases.prep}m`, color: '#60a5fa', pct: taskBlock(t).prepPct },
                        { label: '执行', val: `${t.phases.exec}m`, color: '#818cf8', pct: taskBlock(t).execPct },
                        { label: '结果分析', val: `${t.phases.analysis}m`, color: '#a78bfa', pct: taskBlock(t).analysisPct },
                      ]"
                      :key="ph.label"
                      class="flex-1 rounded-xl p-2.5"
                      :style="{
                        background: isDark ? 'rgba(255,255,255,0.015)' : 'rgba(0,0,0,0.015)',
                        border: `1px solid ${isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.03)'}`,
                      }"
                    >
                      <div class="flex items-center gap-1.5 mb-1">
                        <div class="w-[5px] h-[5px] rounded-sm" :style="{ background: ph.color }" />
                        <span
                          class="text-[10px]"
                          :style="{ color: isDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.3)' }"
                        >{{ ph.label }}</span>
                      </div>
                      <p class="text-[16px]" :style="{ color: ph.color }">{{ ph.val }}</p>
                      <p
                        class="text-[10px]"
                        :style="{ color: isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)' }"
                      >{{ ph.pct.toFixed(0) }}%</p>
                    </div>
                  </div>
                  <div class="grid grid-cols-4 gap-2 mb-2.5">
                    <template v-for="m in [
                      { icon: Gauge, label: 'RPS', val: t.rps, c: '#3b82f6' },
                      { icon: Users, label: 'Vuser', val: t.vuser, c: '#8b5cf6' },
                      { icon: Timer, label: 'P99', val: t.p99, sfx: 'ms', d: 1, c: t.p99 > P99_THRESHOLD ? '#f97316' : '#10b981' },
                      { icon: AlertTriangle, label: 'Err%', val: t.errorRate, sfx: '%', d: 2, c: t.errorRate > 1 ? '#f97316' : '#22c55e' },
                    ]" :key="m.label">
                      <div
                        class="rounded-lg p-2 text-center"
                        :style="{ background: isDark ? 'rgba(255,255,255,0.015)' : 'rgba(0,0,0,0.015)' }"
                      >
                        <component :is="m.icon" :size="14" :color="m.c" class="mx-auto mb-1" />
                        <p
                          class="text-[13px]"
                          :style="{ color: isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.6)' }"
                        >
                          <Anim :value="m.val" :decimals="m.d || 0" :suffix="m.sfx || ''" />
                        </p>
                        <p
                          class="text-[9px]"
                          :style="{ color: isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)' }"
                        >{{ m.label }}</p>
                      </div>
                    </template>
                  </div>
                  <div
                    class="rounded-xl p-2.5"
                    :style="{ background: isDark ? 'rgba(255,255,255,0.015)' : 'rgba(0,0,0,0.015)' }"
                  >
                    <div class="flex items-center gap-1.5 mb-1.5">
                      <Activity :size="12" :color="isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.2)'" />
                      <span
                        class="text-[10px]"
                        :style="{ color: isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.2)' }"
                      >Throughput Wave</span>
                    </div>
                    <WaveSpark :data="t.rpsWave" :color="stColor(t.status)" :h="36" />
                  </div>
                </Motion>
              </AnimatePresence>
            </div>

            <!-- P99 warning -->
            <Motion
              v-if="t.p99 > P99_THRESHOLD && expandedTask !== t.id"
              class="absolute top-2 right-2 px-2 py-1 rounded-lg flex items-center gap-1.5 z-20"
              :animate="{
                boxShadow: [
                  '0 0 4px rgba(249,115,22,0.2)',
                  '0 0 10px rgba(249,115,22,0.5)',
                  '0 0 4px rgba(249,115,22,0.2)',
                ],
              }"
              :transition="{ duration: 1.5, repeat: Infinity }"
              :style="{
                background: isDark ? 'rgba(249,115,22,0.12)' : 'rgba(249,115,22,0.08)',
                border: '1px solid rgba(249,115,22,0.25)',
              }"
            >
              <AlertTriangle :size="10" color="#f97316" />
              <span class="text-[10px]" style="color: #f97316">
                P99: <Anim :value="t.p99" :decimals="1" suffix="ms" />
              </span>
            </Motion>
          </Motion>
        </template>

        <!-- Empty state -->
        <div v-if="dayTasks.length === 0" class="absolute inset-0 flex items-center justify-center">
          <div class="text-center">
            <Clock
              :size="24"
              :color="isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)'"
              class="mx-auto mb-2"
            />
            <p
              class="text-[13px]"
              :style="{ color: isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.2)' }"
            >该日期无任务</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
