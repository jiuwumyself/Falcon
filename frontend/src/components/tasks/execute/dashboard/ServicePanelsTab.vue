<script setup lang="ts">
import { computed } from 'vue'
import { Server } from 'lucide-vue-next'
import GrafanaPanelViewer from '../GrafanaPanelViewer.vue'
import { getMockServiceByName } from '@/lib/servicesMock'
import type { GrafanaPanel, Task, TaskRun } from '@/types/task'

const props = defineProps<{
  task: Task
  run: TaskRun | null
  isDark: boolean
}>()

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
      out.push({
        ...p,
        name: (props.task.service_names.length > 1) ? `${name} · ${p.name}` : p.name,
      })
    }
  }
  return out
})
const servicePanels = computed(() => allPanels.value.filter((p) => p.type === 'service'))

const fromMs = computed<number | null>(
  () => (props.run?.started_at ? new Date(props.run.started_at).getTime() : null),
)
const toMs = computed<number | null>(
  () => (props.run?.finished_at ? new Date(props.run.finished_at).getTime() : Date.now()),
)
</script>

<template>
  <div class="h-full overflow-y-auto p-4">
    <p v-if="!task.service_names?.length" class="text-[12px] py-6 text-center"
       :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">
      <Server :size="20" class="inline-block mb-2" />
      <br>请在 Step 2 选择服务以查看服务面板。
    </p>
    <p v-else-if="!servicePanels.length" class="text-[12px] py-6 text-center"
       :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">
      所选服务（{{ task.service_names.join(' · ') }}）未配置「服务」类 Grafana 面板。
    </p>
    <GrafanaPanelViewer
      v-else
      :panels="servicePanels"
      :from-ms="fromMs"
      :to-ms="toMs"
      :is-dark="isDark"
    />
  </div>
</template>
