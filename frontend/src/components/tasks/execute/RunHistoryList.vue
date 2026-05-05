<script setup lang="ts">
import { computed } from 'vue'
import { Loader, Clock, CheckCircle, XCircle, AlertCircle, Activity, Archive } from 'lucide-vue-next'
import type { TaskRun, RunStatus } from '@/types/task'

const props = defineProps<{
  runs: TaskRun[]
  selectedRunId: string | null
  isDark: boolean
}>()

const emit = defineEmits<{ (e: 'select', runId: string): void }>()

function statusInfo(s: RunStatus) {
  switch (s) {
    case 'pre_checking': return { color: '#94a3b8', icon: Activity }
    case 'pre_check_failed': return { color: '#ef4444', icon: AlertCircle }
    case 'pending': return { color: '#f59e0b', icon: Clock }
    case 'running': return { color: '#10b981', icon: Loader }
    case 'cancelling': return { color: '#f59e0b', icon: Loader }
    case 'success': return { color: '#3b82f6', icon: CheckCircle }
    case 'failed': return { color: '#ef4444', icon: XCircle }
    case 'timeout': return { color: '#ef4444', icon: AlertCircle }
    case 'cancelled': return { color: '#94a3b8', icon: XCircle }
    default: return { color: '#94a3b8', icon: Clock }
  }
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const now = new Date()
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }
  return d.toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

function tooltipFor(run: TaskRun): string {
  const parts = [run.run_id, formatTime(run.started_at || run.last_heartbeat_at)]
  if (run.avg_rps > 0) parts.push(`${run.avg_rps.toFixed(1)} RPS`)
  if (run.error_rate > 0) parts.push(`错误 ${run.error_rate.toFixed(2)}%`)
  return parts.join(' · ')
}

const sorted = computed(() => [...props.runs].sort((a, b) => b.id - a.id))
</script>

<template>
  <div
    class="rounded-xl px-3 py-2 flex items-center gap-2 overflow-x-auto"
    :style="{
      background: isDark ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.45)',
      border: isDark ? '1px solid rgba(255,255,255,0.04)' : '1px solid rgba(0,0,0,0.04)',
    }"
  >
    <span
      class="text-[10px] uppercase tracking-wider whitespace-nowrap mr-1 flex-shrink-0"
      :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
    >历史 ({{ sorted.length }})</span>

    <!-- 空态 -->
    <span
      v-if="!sorted.length"
      class="text-[12px] flex-shrink-0"
      :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)' }"
    >还没有运行记录</span>

    <!-- chip 串 -->
    <button
      v-for="run in sorted"
      :key="run.id"
      type="button"
      :title="tooltipFor(run)"
      class="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11.5px] font-mono transition-all flex-shrink-0"
      :style="{
        background: selectedRunId === run.run_id
          ? (isDark ? 'rgba(59,130,246,0.18)' : 'rgba(59,130,246,0.1)')
          : (isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.025)'),
        border: selectedRunId === run.run_id
          ? '1px solid rgba(59,130,246,0.45)'
          : (isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.05)'),
        color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.7)',
      }"
      @click="emit('select', run.run_id)"
    >
      <component
        :is="statusInfo(run.status).icon"
        :size="11"
        :color="statusInfo(run.status).color"
        :class="{ 'animate-spin': run.status === 'pre_checking' || run.status === 'running' || run.status === 'cancelling' }"
      />
      <span>{{ run.run_id }}</span>
      <Archive
        v-if="run.archived_at"
        :size="10"
        :color="isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.3)'"
      />
    </button>
  </div>
</template>
