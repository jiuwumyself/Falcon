<script setup lang="ts">
import { computed, ref } from 'vue'
import { Motion } from 'motion-v'
import { ChevronLeft, ChevronRight } from 'lucide-vue-next'
import { getCalendarDays, MONTH_NAMES, PEOPLE, SPRING, WEEK_DAYS, type Task } from './data'

const props = defineProps<{
  isDark: boolean
  selectedDate: number
  rimColor: string
  taskDates: Set<number>
  focusedTask: string | null
  tasks: Task[]
}>()

const emit = defineEmits<{ (e: 'selectDate', d: number): void }>()

const today = new Date()
const vy = ref(today.getFullYear())
const vm = ref(today.getMonth())
const todayDate = today.getDate()

const days = computed(() => getCalendarDays(vy.value, vm.value))
const isCurrentMonth = computed(
  () => vm.value === today.getMonth() && vy.value === today.getFullYear(),
)

function prev() {
  if (vm.value === 0) { vm.value = 11; vy.value -= 1 } else vm.value -= 1
}
function next() {
  if (vm.value === 11) { vm.value = 0; vy.value += 1 } else vm.value += 1
}
function onPick(d: { day: number; current: boolean }) {
  if (d.current) emit('selectDate', d.day)
}
function focusedDate(t: string | null) {
  return t ? props.tasks.find((x) => x.id === t)?.date ?? null : null
}
</script>

<template>
  <div class="flex flex-col h-full py-5 px-4" style="width: 290px">
    <!-- Calendar -->
    <div class="mb-4">
      <div class="flex items-center justify-between mb-4 px-1">
        <Motion
          as="button"
          :while-tap="{ scale: 0.8 }"
          class="cursor-pointer p-1.5 rounded-lg"
          :style="{ background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)' }"
          @click="prev"
        >
          <ChevronLeft :size="16" :color="isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)'" />
        </Motion>
        <div class="text-center">
          <p
            class="text-[18px] tracking-wide"
            :style="{ color: isDark ? 'rgba(255,255,255,0.8)' : 'rgba(0,0,0,0.8)' }"
          >{{ MONTH_NAMES[vm] }}</p>
          <p
            class="text-[12px]"
            :style="{ color: isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.2)' }"
          >{{ vy }}</p>
        </div>
        <Motion
          as="button"
          :while-tap="{ scale: 0.8 }"
          class="cursor-pointer p-1.5 rounded-lg"
          :style="{ background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)' }"
          @click="next"
        >
          <ChevronRight :size="16" :color="isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)'" />
        </Motion>
      </div>

      <div class="grid grid-cols-7 mb-1">
        <div v-for="w in WEEK_DAYS" :key="w" class="text-center py-1">
          <span
            class="text-[11px] tracking-wider"
            :style="{ color: isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.2)' }"
          >{{ w }}</span>
        </div>
      </div>

      <div class="grid grid-cols-7 gap-y-0.5">
        <template v-for="(d, i) in days" :key="i">
          <Motion
            as="button"
            :while-tap="{ scale: 0.8 }"
            class="relative w-full aspect-square flex flex-col items-center justify-center cursor-pointer"
            :transition="{ type: 'spring', ...SPRING }"
            @click="onPick(d)"
          >
            <Motion
              v-if="d.current && d.day === todayDate && isCurrentMonth"
              class="absolute inset-[2px] rounded-full"
              :animate="{
                boxShadow: [
                  `0 0 8px ${rimColor}30, inset 0 0 4px ${rimColor}15`,
                  `0 0 16px ${rimColor}50, inset 0 0 8px ${rimColor}25`,
                  `0 0 8px ${rimColor}30, inset 0 0 4px ${rimColor}15`,
                ],
                background: [
                  `radial-gradient(circle, ${rimColor}08, transparent)`,
                  `radial-gradient(circle, ${rimColor}15, transparent)`,
                  `radial-gradient(circle, ${rimColor}08, transparent)`,
                ],
              }"
              :transition="{ duration: 3, repeat: Infinity, ease: 'easeInOut' }"
              :style="{ border: `1.5px solid ${rimColor}40` }"
            />
            <Motion
              v-else-if="d.current && d.day === selectedDate && isCurrentMonth"
              layoutId="calSel"
              class="absolute inset-[3px] rounded-full"
              :style="{ background: '#3b82f6', opacity: 0.15 }"
              :transition="{ type: 'spring', ...SPRING }"
            />
            <Motion
              v-else-if="d.current && focusedDate(focusedTask) === d.day"
              :initial="{ opacity: 0, scale: 0.5 }"
              :animate="{ opacity: 1, scale: 1 }"
              :exit="{ opacity: 0, scale: 0.5 }"
              class="absolute inset-[2px] rounded-full"
              :style="{
                background: `radial-gradient(circle, ${rimColor}20, transparent)`,
                boxShadow: `0 0 12px ${rimColor}30`,
              }"
              :transition="{ type: 'spring', ...SPRING }"
            />
            <span
              class="text-[14px] relative z-10"
              :style="{
                color: d.current && d.day === todayDate && isCurrentMonth ? rimColor
                  : d.current && d.day === selectedDate && isCurrentMonth ? '#3b82f6'
                    : !d.current ? (isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.1)')
                      : isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)',
              }"
            >{{ d.day }}</span>
            <div
              v-if="d.current && taskDates.has(d.day)"
              class="w-[5px] h-[5px] rounded-full absolute bottom-[3px]"
              :style="{
                background: d.day === todayDate && isCurrentMonth ? rimColor : 'rgba(59,130,246,0.5)',
                boxShadow: `0 0 4px rgba(59,130,246,0.3)`,
              }"
            />
          </Motion>
        </template>
      </div>
    </div>

    <div
      class="mx-2 h-[1px] mb-3"
      :style="{ background: `linear-gradient(90deg, transparent, ${rimColor}15, transparent)` }"
    />

    <p
      class="text-[11px] uppercase tracking-[0.2em] px-2 mb-3"
      :style="{ color: isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.2)' }"
    >Team Matrix</p>
    <div class="flex-1 overflow-y-auto flex flex-col gap-2">
      <Motion
        v-for="(p, i) in PEOPLE"
        :key="p.name"
        :initial="{ opacity: 0, x: -8 }"
        :animate="{ opacity: 1, x: 0 }"
        :transition="{ delay: i * 0.06, type: 'spring', ...SPRING }"
        class="flex items-center gap-3 px-2.5 py-2.5 rounded-xl cursor-pointer group"
        :style="{ background: isDark ? 'rgba(255,255,255,0.015)' : 'rgba(0,0,0,0.01)' }"
      >
        <div class="relative flex-shrink-0">
          <svg width="44" height="44" viewBox="0 0 44 44" class="absolute inset-0">
            <circle
              cx="22"
              cy="22"
              r="18"
              fill="none"
              :stroke="isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'"
              stroke-width="2.5"
            />
            <circle
              cx="22"
              cy="22"
              r="18"
              fill="none"
              :stroke="p.status === 'running' ? '#22c55e' : '#3b82f6'"
              stroke-width="2.5"
              :stroke-dasharray="2 * Math.PI * 18"
              :stroke-dashoffset="2 * Math.PI * 18 - p.progress * 2 * Math.PI * 18"
              stroke-linecap="round"
              transform="rotate(-90 22 22)"
              opacity="0.8"
            />
          </svg>
          <div
            class="w-11 h-11 rounded-xl flex items-center justify-center text-[12px] text-white relative z-10"
            :style="{
              background: `linear-gradient(135deg, ${p.color}dd, ${p.color}88)`,
              boxShadow: `0 3px 10px ${p.color}25, inset 0 1px 0 rgba(255,255,255,0.15), inset 0 -1px 0 rgba(0,0,0,0.15)`,
            }"
          >{{ p.avatar }}</div>
        </div>
        <div class="min-w-0 flex-1">
          <p
            class="text-[13px] truncate"
            :style="{ color: isDark ? 'rgba(255,255,255,0.65)' : 'rgba(0,0,0,0.65)' }"
          >{{ p.name }}</p>
          <p
            class="text-[11px]"
            :style="{ color: isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.25)' }"
          >{{ p.role }}</p>
        </div>
        <div class="flex items-center gap-1.5">
          <div
            class="w-[6px] h-[6px] rounded-full"
            :style="{
              background: p.status === 'running' ? '#22c55e' : '#3b82f6',
              boxShadow: `0 0 6px ${p.status === 'running' ? '#22c55e' : '#3b82f6'}40`,
            }"
          />
          <span
            class="text-[10px]"
            :style="{ color: p.status === 'running' ? '#22c55e' : '#3b82f6' }"
          >{{ p.status === 'running' ? '执行中' : '分析中' }}</span>
        </div>
      </Motion>
    </div>
  </div>
</template>
