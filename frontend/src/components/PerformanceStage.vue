<script setup lang="ts">
import { computed, ref } from 'vue'
import { Motion } from 'motion-v'
import { useRouter } from 'vue-router'
import { useTheme } from '@/composables/useTheme'
import { TASKS } from './perf/data'
import { useRimColor } from './perf/useRimColor'
import ChronosNerve from './perf/ChronosNerve.vue'
import MetricsColumn from './perf/MetricsColumn.vue'
import TemporalColumn from './perf/TemporalColumn.vue'

const { theme } = useTheme()
const isDark = computed(() => theme.value === 'dark')
const rimColor = useRimColor()
const router = useRouter()

const activeBiz = ref('all')
const selectedDate = ref(new Date().getDate())
const focusedTask = ref<string | null>(null)

const taskDates = computed(() => new Set(TASKS.map((t) => t.date)))
const filteredTasks = computed(() => TASKS)
const dofActive = computed(() => focusedTask.value !== null)

function handleCreate() {
  // Jump to the task-wizard page so the URL reflects state and refresh keeps the user there.
  router.push('/performance/tasks')
}

const panelGlass = computed(() => ({
  background: isDark.value ? 'rgba(255,255,255,0.025)' : 'rgba(255,255,255,0.45)',
  backdropFilter: 'blur(80px)',
  WebkitBackdropFilter: 'blur(80px)',
  borderRadius: '24px',
  boxShadow: `
    inset 0 1px 0 0 rgba(255,255,255,${isDark.value ? 0.06 : 0.6}),
    inset 0 -1px 0 0 rgba(0,0,0,${isDark.value ? 0.08 : 0.02}),
    0 8px 40px rgba(0,0,0,${isDark.value ? 0.2 : 0.06}),
    0 0 0 1px ${rimColor.value}08
  `,
  border: `1px solid ${rimColor.value}${isDark.value ? '0a' : '12'}`,
}))
</script>

<template>
  <!-- 3-column layout (wizard lives on its own route /performance/tasks) -->
  <div class="w-full h-full flex items-stretch gap-2.5 overflow-hidden">
    <!-- Column 1: Chronos Nerve -->
    <div class="flex-shrink-0 overflow-hidden" :style="panelGlass">
      <ChronosNerve
        :is-dark="isDark"
        :tasks="filteredTasks"
        :rim-color="rimColor"
        :active-biz="activeBiz"
        @focus="(id) => (focusedTask = id)"
        @select-biz="(id) => (activeBiz = id)"
        @create="handleCreate"
      />
    </div>

      <!-- Column 2: Metrics & Consumption -->
      <Motion
        class="flex-1 min-w-0 overflow-hidden"
        :style="panelGlass"
        :animate="{
          filter: dofActive ? 'blur(1px)' : 'blur(0px)',
          opacity: dofActive ? 0.8 : 1,
        }"
        :transition="{ duration: 0.4 }"
      >
        <MetricsColumn
          :is-dark="isDark"
          :tasks="filteredTasks"
          :focused-task="focusedTask"
          :rim-color="rimColor"
          :selected-date="selectedDate"
          @select-date="(d) => (selectedDate = d)"
        />
      </Motion>

      <!-- Column 3: Temporal & Personnel -->
      <Motion
        class="flex-shrink-0 overflow-hidden"
        :style="panelGlass"
        :animate="{
          filter: dofActive ? 'blur(1.5px)' : 'blur(0px)',
          opacity: dofActive ? 0.75 : 1,
        }"
        :transition="{ duration: 0.4 }"
      >
        <TemporalColumn
          :is-dark="isDark"
          :selected-date="selectedDate"
          :rim-color="rimColor"
          :task-dates="taskDates"
          :focused-task="focusedTask"
          :tasks="filteredTasks"
          @select-date="(d) => (selectedDate = d)"
        />
      </Motion>
  </div>
</template>
