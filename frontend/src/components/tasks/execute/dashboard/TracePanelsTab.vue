<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { GitBranch, Loader } from 'lucide-vue-next'
import GrafanaPanelViewer from '../GrafanaPanelViewer.vue'
import SlowTraceTable from './trace/SlowTraceTable.vue'
import { useServices } from '@/composables/useServices'
import { runsApi } from '@/lib/api'
import type { GrafanaPanel, PinpointTrace, Task, TaskRun } from '@/types/task'

const props = defineProps<{
  task: Task
  run: TaskRun | null
  isDark: boolean
}>()

const { getByName } = useServices()

const allPanels = computed<GrafanaPanel[]>(() => {
  const out: GrafanaPanel[] = []
  const seen = new Set<string>()
  for (const name of props.task.service_names || []) {
    const svc = getByName(name)
    if (!svc) continue
    for (const p of svc.grafana_panels) {
      const key = `${name}::${p.name}::${p.url}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push({
        ...p,
        name: (props.task.service_names.length > 1) ? `${name} · ${p.name}` : p.name,
      })
    }
  }
  return out
})
const tracePanels = computed(() => allPanels.value.filter((p) => p.type === 'trace'))

const fromMs = computed<number | null>(
  () => (props.run?.started_at ? new Date(props.run.started_at).getTime() : null),
)
const toMs = computed<number | null>(
  () => (props.run?.finished_at ? new Date(props.run.finished_at).getTime() : Date.now()),
)

// § 11 Pinpoint 慢 trace：仅终态时拉
const TERMINAL_STATUSES = ['success', 'failed', 'timeout', 'cancelled', 'pre_check_failed']
const isTerminal = computed(
  () => !!props.run?.status && TERMINAL_STATUSES.includes(props.run.status),
)
const traces = ref<PinpointTrace[]>([])
const tracesLoading = ref(false)

async function loadTraces() {
  if (!props.run?.run_id || !isTerminal.value) {
    traces.value = []
    return
  }
  tracesLoading.value = true
  try {
    traces.value = await runsApi.pinpointTraces(props.run.run_id)
  } catch {
    traces.value = []  // 静默失败：endpoint 不可达 / 后端 collector skip
  } finally {
    tracesLoading.value = false
  }
}

watch([() => props.run?.run_id, isTerminal], loadTraces)
onMounted(loadTraces)
</script>

<template>
  <div class="h-full overflow-y-auto p-4 flex flex-col gap-4">
    <!-- 顶部：原 Grafana iframe 链路面板 -->
    <p v-if="!task.service_names?.length" class="text-[12px] py-6 text-center"
       :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">
      <GitBranch :size="20" class="inline-block mb-2" />
      <br>请在 Step 2 选择服务以查看链路面板。
    </p>
    <p v-else-if="!tracePanels.length" class="text-[12px] py-3 text-center"
       :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">
      所选服务（{{ task.service_names.join(' · ') }}）未配置「链路」类 Grafana 面板。
    </p>
    <GrafanaPanelViewer
      v-else
      :panels="tracePanels"
      :from-ms="fromMs"
      :to-ms="toMs"
      :is-dark="isDark"
    />

    <!-- 底部：§ 11 Pinpoint 慢 trace 列表（终态显示） -->
    <div v-if="task.service_names?.length" class="flex flex-col gap-2">
      <div
        class="flex items-center gap-1.5 px-1"
        :style="{ color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.65)' }"
      >
        <span class="w-0.5 h-3.5 rounded-full" :style="{ background: '#a855f7' }" />
        <span class="text-[12px] font-medium">Pinpoint 慢 trace（{{ traces.length }}）</span>
        <Loader v-if="tracesLoading" :size="11" class="animate-spin opacity-60 ml-1" />
      </div>

      <p
        v-if="!isTerminal"
        class="text-[11px] py-3 text-center"
        :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.45)' }"
      >
        run 终态后自动从 Pinpoint 拉取慢于 P99 的 trace 元数据
      </p>
      <p
        v-else-if="!tracesLoading && !traces.length"
        class="text-[11px] py-3 text-center"
        :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.45)' }"
      >
        本次 run 未拉到 Pinpoint 慢 trace。可能原因：Pinpoint 未启用（admin） / Service
        未配 pinpoint_app / Pinpoint 暂不可达 / 慢于 P99 的 trace 不存在
      </p>
      <SlowTraceTable v-else :traces="traces" :is-dark="isDark" />
    </div>
  </div>
</template>
