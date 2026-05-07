<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Activity, Server, GitBranch, AlertCircle } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import { getMockServiceByName } from '@/lib/servicesMock'
import type { GrafanaPanel, Task, TaskRun } from '@/types/task'
import GrafanaPanelViewer from './GrafanaPanelViewer.vue'

const props = defineProps<{
  task: Task
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
const timelineError = ref('')

async function loadTimeline() {
  if (!props.run?.run_id) {
    timeline.value = null
    return
  }
  try {
    timeline.value = await api<TimelineResp>(`/runs/${props.run.run_id}/timeline/`)
    timelineError.value = ''
  } catch (e) {
    timelineError.value = e instanceof ApiError ? e.humanMessage : String(e)
  }
}

watch(() => props.run?.run_id, loadTimeline)
onMounted(loadTimeline)

// 服务 / 链路面板：遍历 task.service_names 取并集
const allPanels = computed<GrafanaPanel[]>(() => {
  const out: GrafanaPanel[] = []
  const seen = new Set<string>()
  for (const name of props.task.service_names || []) {
    const svc = getMockServiceByName(name)
    if (!svc) continue
    for (const p of svc.grafana_panels) {
      const key = `${name}::${p.name}::${p.url}`
      if (seen.has(key)) continue
      seen.add(key)
      // 在 panel 名前加服务前缀，多服务时区分
      out.push({
        ...p,
        name: (props.task.service_names.length > 1) ? `${name} · ${p.name}` : p.name,
      })
    }
  }
  return out
})
const servicePanels = computed(() => allPanels.value.filter((p) => p.type === 'service'))
const tracePanels = computed(() => allPanels.value.filter((p) => p.type === 'trace'))

const fromMs = computed<number | null>(() => {
  const s = timeline.value?.started_at
  return s ? new Date(s).getTime() : null
})
const toMs = computed<number | null>(() => {
  const t = timeline.value?.finished_at
  return t ? new Date(t).getTime() : Date.now()
})

const totalSpanMs = computed(() => {
  const ph = timeline.value?.phases || []
  if (!ph.length) return 0
  return Math.max(...ph.map((p) => p.end)) - Math.min(...ph.map((p) => p.start))
})

function pctWidth(p: TimelinePhase): string {
  if (!totalSpanMs.value) return '0%'
  return `${Math.max(((p.end - p.start) / totalSpanMs.value) * 100, 1)}%`
}

const PHASE_COLORS: Record<string, string> = {
  pre_check: '#9ca3af',
  ramp_up: '#3b82f6',
  steady: '#10b981',
  cool_down: '#a78bfa',
}

function fmtDuration(ms: number): string {
  if (ms <= 0) return '-'
  const sec = Math.round(ms / 1000)
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60), s = sec % 60
  return `${m}m${s ? s + 's' : ''}`
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <!-- 子段 1：运行情况 ──────────────────────── -->
    <section
      class="rounded-xl p-3"
      :style="{
        background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)',
        border: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
      }"
    >
      <div class="flex items-center gap-2 mb-2">
        <Activity :size="13" color="#10b981" />
        <span class="text-[12px]" :style="{ color: isDark ? '#fff' : '#1a1a2e' }">运行情况</span>
        <span v-if="run" class="text-[10px] ml-auto"
              :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.45)' }">
          {{ run.status }} · run_id {{ run.run_id }}
        </span>
      </div>

      <p v-if="timelineError" class="text-[11px] text-red-500 flex items-center gap-1 mb-2">
        <AlertCircle :size="11" /> {{ timelineError }}
      </p>

      <div v-if="!timeline || !timeline.phases.length" class="text-[11px] py-3 text-center"
           :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">
        暂无运行数据。启动 run 后此处显示甘特时间轴。
      </div>

      <div v-else>
        <!-- 甘特图 -->
        <div class="flex h-6 rounded overflow-hidden">
          <div
            v-for="p in timeline.phases"
            :key="p.name"
            class="flex items-center justify-center text-[9px] text-white truncate px-1"
            :style="{
              width: pctWidth(p),
              background: PHASE_COLORS[p.name] || '#6b7280',
            }"
            :title="`${p.label}: ${fmtDuration(p.end - p.start)}`"
          >
            {{ p.label }}
          </div>
        </div>
        <!-- 阶段时长说明 -->
        <div class="grid grid-cols-4 gap-2 mt-2">
          <div v-for="p in timeline.phases" :key="`d-${p.name}`"
               class="flex flex-col">
            <span class="text-[10px]"
                  :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.5)' }">
              <span class="inline-block w-2 h-2 rounded mr-1"
                    :style="{ background: PHASE_COLORS[p.name] || '#6b7280' }" />
              {{ p.label }}
            </span>
            <span class="text-[12px]" :style="{ color: isDark ? '#fff' : '#1a1a2e' }">
              {{ fmtDuration(p.end - p.start) }}
            </span>
          </div>
        </div>
      </div>
    </section>

    <!-- 子段 2：服务情况 ──────────────────────── -->
    <section
      class="rounded-xl p-3"
      :style="{
        background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)',
        border: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
      }"
    >
      <div class="flex items-center gap-2 mb-2">
        <Server :size="13" color="#3b82f6" />
        <span class="text-[12px]" :style="{ color: isDark ? '#fff' : '#1a1a2e' }">服务情况</span>
        <span v-if="task.service_names?.length" class="text-[10px] ml-auto"
              :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.45)' }">
          已绑定：{{ task.service_names.join(' · ') }}
        </span>
      </div>
      <p v-if="!task.service_names?.length" class="text-[11px] py-3 text-center"
         :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">
        请在 Step 2 选择服务。
      </p>
      <p v-else-if="!servicePanels.length" class="text-[11px] py-3 text-center"
         :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">
        所选服务未配置「服务」类 Grafana 面板。
      </p>
      <GrafanaPanelViewer
        v-else
        :panels="servicePanels"
        :from-ms="fromMs"
        :to-ms="toMs"
        :is-dark="isDark"
      />
    </section>

    <!-- 子段 3：链路情况 ──────────────────────── -->
    <section
      class="rounded-xl p-3"
      :style="{
        background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)',
        border: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
      }"
    >
      <div class="flex items-center gap-2 mb-2">
        <GitBranch :size="13" color="#a78bfa" />
        <span class="text-[12px]" :style="{ color: isDark ? '#fff' : '#1a1a2e' }">链路情况</span>
      </div>
      <p v-if="!task.service_names?.length" class="text-[11px] py-3 text-center"
         :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">
        请在 Step 2 选择服务。
      </p>
      <p v-else-if="!tracePanels.length" class="text-[11px] py-3 text-center"
         :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">
        所选服务未配置「链路」类 Grafana 面板。
      </p>
      <GrafanaPanelViewer
        v-else
        :panels="tracePanels"
        :from-ms="fromMs"
        :to-ms="toMs"
        :is-dark="isDark"
      />
    </section>
  </div>
</template>
