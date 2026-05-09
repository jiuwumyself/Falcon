<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Cpu, Activity, FileText, AlertCircle } from 'lucide-vue-next'
import GrafanaPanelViewer from '../GrafanaPanelViewer.vue'
import { useServices } from '@/composables/useServices'
import type { GrafanaPanel, Task, TaskRun } from '@/types/task'

// G4：JVM tab v1（按 plan §4.5 落地）
//
// v1 能力 = 时序 metric 从 Grafana iframe（heap usage / GC count / GC pause /
// thread count），按服务切 sub-tab；dump 按钮组 disabled + tooltip 等 Arthas
// 接入立项后启用（v2）。
//
// 数据来源 = Service.grafana_panels filter type='jvm'，admin 在每个 Service 配
// 该服务的 JVM 面板。

const props = defineProps<{
  task: Task
  run: TaskRun | null
  isDark: boolean
}>()

const { getByName } = useServices()

const serviceNames = computed(() => props.task.service_names || [])
const activeService = ref<string>('')

watch(serviceNames, (names) => {
  if (!names.length) {
    activeService.value = ''
    return
  }
  if (!names.includes(activeService.value)) {
    activeService.value = names[0]
  }
}, { immediate: true })

const jvmPanels = computed<GrafanaPanel[]>(() => {
  if (!activeService.value) return []
  const svc = getByName(activeService.value)
  if (!svc) return []
  return svc.grafana_panels.filter((p) => p.type === 'jvm')
})

const fromMs = computed<number | null>(
  () => (props.run?.started_at ? new Date(props.run.started_at).getTime() : null),
)
const toMs = computed<number | null>(
  () => (props.run?.finished_at ? new Date(props.run.finished_at).getTime() : Date.now()),
)

const dumpDisabledTooltip = '需接入 Arthas tunnel（v2 立项），当前 v1 仅展示 Grafana JVM 时序 metric'
</script>

<template>
  <div class="h-full flex flex-col overflow-hidden">
    <!-- 服务切换 sub-tab：仅多服务时显示 -->
    <div
      v-if="serviceNames.length > 1"
      class="flex items-center gap-0 px-3 flex-shrink-0"
      :style="{
        borderBottom: `1px solid ${isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'}`,
      }"
    >
      <button
        v-for="name in serviceNames"
        :key="name"
        class="flex items-center gap-1 px-3 py-1.5 text-[11.5px] cursor-pointer flex-shrink-0"
        :style="{
          color: activeService === name
            ? (isDark ? '#fff' : '#1a1a2e')
            : (isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.55)'),
          borderBottom: `2px solid ${activeService === name ? '#a855f7' : 'transparent'}`,
        }"
        @click="activeService = name"
      >
        <Cpu :size="11" />
        {{ name }}
      </button>
    </div>

    <!-- 内容：上 Grafana iframe + 下 dump 按钮区 -->
    <div class="flex-1 min-h-0 flex flex-col p-4 gap-3 overflow-y-auto">
      <!-- 占位：未选服务 -->
      <p
        v-if="!serviceNames.length"
        class="text-[12px] py-6 text-center"
        :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
      >
        <Cpu :size="20" class="inline-block mb-2" />
        <br>请在 Step 2 选择服务以查看 JVM 指标。
      </p>

      <!-- 占位：所选服务无 JVM 面板 -->
      <p
        v-else-if="!jvmPanels.length"
        class="text-[12px] py-6 text-center"
        :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
      >
        <Activity :size="20" class="inline-block mb-2" />
        <br>服务「{{ activeService }}」未配置 JVM 类 Grafana 面板。
        <br>
        <span class="text-[10.5px] opacity-70">
          admin → Service → grafana_panels 加 type='jvm' 的面板
        </span>
      </p>

      <!-- 时序 metric：复用 GrafanaPanelViewer 嵌入 iframe -->
      <div v-else class="flex-1 min-h-[400px]">
        <GrafanaPanelViewer
          :panels="jvmPanels"
          :from-ms="fromMs"
          :to-ms="toMs"
          :is-dark="isDark"
        />
      </div>

      <!-- Dump 按钮区（v1 全部 disabled） -->
      <div
        class="rounded-lg p-3 flex-shrink-0"
        :style="{
          background: isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)',
          border: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
        }"
      >
        <div
          class="flex items-center gap-1.5 mb-2 text-[11.5px]"
          :style="{ color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.65)' }"
        >
          <FileText :size="13" />
          重型诊断 dump
          <span
            class="ml-auto inline-flex items-center gap-1 text-[10.5px] px-1.5 py-0.5 rounded"
            :style="{
              background: 'rgba(245,158,11,0.12)',
              color: '#f59e0b',
              border: '1px solid rgba(245,158,11,0.25)',
            }"
          >
            <AlertCircle :size="10" />
            待接入 Arthas
          </span>
        </div>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="action in [
              { label: 'Thread Dump', desc: '看死锁 / 飞起的线程' },
              { label: 'Heap Snapshot', desc: '看泄漏 / OOM 对象' },
              { label: 'GC Log Tail', desc: '看完整 GC 历史' },
            ]"
            :key="action.label"
            class="flex flex-col items-start gap-0.5 px-3 py-2 rounded-lg text-[11.5px] cursor-not-allowed opacity-50"
            :style="{
              background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)',
              border: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
              color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)',
            }"
            disabled
            :title="dumpDisabledTooltip"
          >
            <span class="font-medium">{{ action.label }}</span>
            <span class="text-[10px] opacity-70">{{ action.desc }}</span>
          </button>
        </div>
        <p
          class="text-[10.5px] mt-2 px-1"
          :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
        >
          {{ dumpDisabledTooltip }}
        </p>
      </div>
    </div>
  </div>
</template>
