<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Activity, AlertCircle } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import type { TaskRun } from '@/types/task'

const props = defineProps<{
  run: TaskRun | null
  isDark: boolean
}>()

interface TimelinePhase {
  name: string
  start: number
  end: number
  label: string
}
interface TimelineResp {
  phases: TimelinePhase[]
  started_at: string | null
  finished_at: string | null
  duration_seconds: number
  ramp_up_seconds: number
}

const timeline = ref<TimelineResp | null>(null)
const error = ref('')

async function loadTimeline() {
  if (!props.run?.run_id) {
    timeline.value = null
    return
  }
  try {
    timeline.value = await api<TimelineResp>(`/runs/${props.run.run_id}/timeline/`)
    error.value = ''
  } catch (e) {
    error.value = e instanceof ApiError ? e.humanMessage : String(e)
  }
}

watch(() => props.run?.run_id, loadTimeline)
onMounted(loadTimeline)

const PHASE_COLORS: Record<string, string> = {
  pre_check: '#9ca3af',
  ramp_up: '#3b82f6',
  steady: '#10b981',
  cool_down: '#a78bfa',
}

const totalSpanMs = computed(() => {
  const ph = timeline.value?.phases || []
  if (!ph.length) return 0
  return Math.max(...ph.map((p) => p.end)) - Math.min(...ph.map((p) => p.start))
})

function pctWidth(p: TimelinePhase): string {
  if (!totalSpanMs.value) return '0%'
  return `${Math.max(((p.end - p.start) / totalSpanMs.value) * 100, 1)}%`
}

function fmtDuration(ms: number): string {
  if (ms <= 0) return '-'
  const sec = Math.round(ms / 1000)
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60), s = sec % 60
  return `${m}m${s ? s + 's' : ''}`
}

function fmtTime(ts: string | null): string {
  if (!ts) return '-'
  const d = new Date(ts)
  return `${d.toLocaleDateString()} ${d.toLocaleTimeString()}`
}
</script>

<template>
  <div class="h-full overflow-y-auto p-4 flex flex-col gap-4">
    <p v-if="error" class="text-[11px] text-red-500 flex items-center gap-1">
      <AlertCircle :size="11" /> {{ error }}
    </p>

    <div v-if="!timeline || !timeline.phases.length" class="text-[12px] py-6 text-center"
         :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">
      <Activity :size="20" class="inline-block mb-2" />
      <p>暂无运行数据。启动 run 后此处显示甘特时间轴。</p>
    </div>

    <template v-else>
      <!-- 甘特条 -->
      <div>
        <p class="text-[11px] mb-2"
           :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }">
          运行时间轴 · {{ fmtTime(timeline.started_at) }} → {{ fmtTime(timeline.finished_at) }}
        </p>
        <div class="flex h-7 rounded overflow-hidden">
          <div
            v-for="p in timeline.phases"
            :key="p.name"
            class="flex items-center justify-center text-[10px] text-white truncate px-1.5"
            :style="{
              width: pctWidth(p),
              background: PHASE_COLORS[p.name] || '#6b7280',
            }"
            :title="`${p.label}: ${fmtDuration(p.end - p.start)}`"
          >{{ p.label }}</div>
        </div>
      </div>

      <!-- 阶段时长卡片 -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div v-for="p in timeline.phases" :key="`d-${p.name}`"
             class="rounded-lg p-3"
             :style="{
               background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)',
               border: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
             }">
          <p class="text-[10px] flex items-center gap-1.5"
             :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.55)' }">
            <span class="inline-block w-2 h-2 rounded"
                  :style="{ background: PHASE_COLORS[p.name] || '#6b7280' }" />
            {{ p.label }}
          </p>
          <p class="text-[18px] mt-1"
             :style="{ color: isDark ? '#fff' : '#1a1a2e' }">
            {{ fmtDuration(p.end - p.start) }}
          </p>
        </div>
      </div>
    </template>
  </div>
</template>
