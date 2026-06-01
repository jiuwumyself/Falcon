<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  RefreshCw, Plus, Trash2, Server, Loader, AlertCircle,
  CheckCircle2, BarChart2,
} from 'lucide-vue-next'
import { ApiError, loadGeneratorsApi } from '@/lib/api'
import type { LoadGenerator } from '@/types/task'

const props = defineProps<{
  vusers: number
  isDark: boolean
  modelValue: number[]      // 选中的 LoadGenerator id 列表
  busy?: boolean            // run 进行中时禁止改选
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: number[]): void
  (e: 'view-metrics', lg: LoadGenerator): void
}>()

const lgs = ref<LoadGenerator[]>([])
const loading = ref(false)
const scaling = ref(false)
const error = ref('')
const scaleCount = ref(3)

let pollTimer: number | undefined

const selected = computed(() => new Set(props.modelValue))
const totalCapacity = computed(() =>
  lgs.value
    .filter((g) => selected.value.has(g.id))
    .reduce((sum, g) => sum + g.max_vusers, 0),
)
const recommended = computed(() => Math.max(1, Math.ceil(props.vusers / 100)))

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    lgs.value = await loadGeneratorsApi.list()
    // 初次或 modelValue 为空时：自动选 idle 的前 N 台凑够 vusers
    if (props.modelValue.length === 0) {
      autoSelect()
    } else {
      // 清掉已不在线的
      const alive = new Set(lgs.value.map((g) => g.id))
      const filtered = props.modelValue.filter((id) => alive.has(id))
      if (filtered.length !== props.modelValue.length) {
        emit('update:modelValue', filtered)
      }
    }
  } catch (e) {
    error.value = e instanceof ApiError ? e.humanMessage : String(e)
  } finally {
    loading.value = false
  }
}

function autoSelect() {
  const idle = lgs.value
    .filter((g) => g.status === 'idle')
    .sort((a, b) => b.max_vusers - a.max_vusers)
  let need = props.vusers
  const picks: number[] = []
  for (const g of idle) {
    if (need <= 0) break
    picks.push(g.id)
    need -= g.max_vusers
  }
  emit('update:modelValue', picks)
}

function toggle(id: number) {
  if (props.busy) return
  const set = new Set(props.modelValue)
  if (set.has(id)) set.delete(id)
  else set.add(id)
  emit('update:modelValue', Array.from(set))
}

async function doScaleUp() {
  if (scaling.value || scaleCount.value < 1) return
  scaling.value = true
  error.value = ''
  try {
    await loadGeneratorsApi.scaleUp(scaleCount.value)
    // 给 agent 5-15s 注册时间，定时拉刷新
    setTimeout(refresh, 6000)
    setTimeout(refresh, 14000)
  } catch (e) {
    error.value = e instanceof ApiError ? e.humanMessage : String(e)
  } finally {
    scaling.value = false
  }
}

async function releaseIdle() {
  if (props.busy) return
  if (!confirm('释放所有当前 idle 的压力源？正在跑的不受影响。')) return
  scaling.value = true
  error.value = ''
  try {
    await loadGeneratorsApi.scaleDown({ idle_only: true })
    await refresh()
  } catch (e) {
    error.value = e instanceof ApiError ? e.humanMessage : String(e)
  } finally {
    scaling.value = false
  }
}

function statusColor(s: string): string {
  if (s === 'idle') return '#10b981'
  if (s === 'busy') return '#f59e0b'
  if (s === 'lost') return '#ef4444'
  return '#6b7280'
}

onMounted(() => {
  refresh()
  // 30s 自动刷新一次（捕获新 register 的 agent）
  pollTimer = window.setInterval(refresh, 30000)
})
onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div
    class="rounded-xl p-3"
    :style="{
      background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)',
      border: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
    }"
  >
    <!-- 顶部容量摘要 -->
    <div class="flex items-center gap-3 mb-2.5">
      <Server :size="14" :color="isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)'" />
      <span class="text-[12px]" :style="{ color: isDark ? '#fff' : '#1a1a2e' }">
        压力源
      </span>
      <span class="text-[11px]" :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.5)' }">
        并发 {{ vusers }} · 建议 ≥{{ recommended }} 台 · 已选容量
        <span :style="{ color: totalCapacity >= vusers ? '#10b981' : '#f59e0b' }">
          {{ totalCapacity }}
        </span>
        / {{ vusers }}
      </span>
      <button
        class="ml-auto flex items-center gap-1 text-[11px] cursor-pointer disabled:opacity-50"
        :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }"
        :disabled="loading"
        @click="refresh"
      >
        <Loader v-if="loading" :size="10" class="animate-spin" />
        <RefreshCw v-else :size="10" />
        刷新
      </button>
    </div>

    <p v-if="error" class="text-[11px] text-red-500 flex items-center gap-1 mb-2">
      <AlertCircle :size="11" /> {{ error }}
    </p>

    <!-- 表格 / 空态 -->
    <div v-if="!lgs.length" class="text-[11px] py-3 text-center"
         :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">
      暂无压力源。点下方「+ 扩容」拉起 agent，或确认 docker-compose 已启 agent 服务。
    </div>
    <div v-else class="flex flex-col gap-1.5 max-h-[180px] overflow-y-auto pr-1">
      <button
        v-for="g in lgs"
        :key="g.id"
        class="flex items-center gap-2 px-2 py-1.5 rounded text-[11px] cursor-pointer text-left"
        :class="{ 'opacity-60 cursor-not-allowed': props.busy }"
        :style="{
          background: selected.has(g.id)
            ? (isDark ? 'rgba(59,130,246,0.12)' : 'rgba(59,130,246,0.08)')
            : 'transparent',
          border: `1px solid ${selected.has(g.id)
            ? (isDark ? 'rgba(59,130,246,0.3)' : 'rgba(59,130,246,0.25)')
            : 'transparent'}`,
        }"
        @click="toggle(g.id)"
      >
        <span
          class="flex items-center justify-center w-3.5 h-3.5 rounded-sm flex-shrink-0"
          :style="{
            background: selected.has(g.id) ? '#3b82f6' : 'transparent',
            border: `1px solid ${selected.has(g.id)
              ? '#3b82f6'
              : (isDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.25)')}`,
          }"
        >
          <CheckCircle2 v-if="selected.has(g.id)" :size="10" color="#fff" />
        </span>
        <span class="flex-1 min-w-0 truncate"
              :style="{ color: isDark ? '#fff' : '#1a1a2e' }">
          {{ g.pod_name }}
        </span>
        <span class="text-[10px]"
              :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.5)' }">
          {{ g.cpu_cores }}C/{{ g.memory_gb }}G · cap {{ g.max_vusers }}
        </span>
        <span
          class="text-[10px] px-1.5 py-0.5 rounded"
          :style="{
            background: `${statusColor(g.status)}1f`,
            color: statusColor(g.status),
          }"
        >{{ g.status }}</span>
        <button
          class="flex items-center justify-center cursor-pointer"
          :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }"
          title="查看系统指标"
          @click.stop="emit('view-metrics', g)"
        >
          <BarChart2 :size="12" />
        </button>
      </button>
    </div>

    <!-- 扩容 / 缩容控件 -->
    <div class="flex items-center gap-1.5 mt-2.5 pt-2.5"
         :style="{
           borderTop: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
         }">
      <input
        v-model.number="scaleCount"
        type="number"
        min="1"
        max="20"
        class="w-12 px-1.5 py-0.5 rounded text-[11px] text-center outline-none"
        :style="{
          background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
          color: isDark ? '#fff' : '#1a1a2e',
          border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
        }"
      />
      <button
        class="flex items-center gap-1 px-2 py-1 rounded text-[11px] cursor-pointer disabled:opacity-50"
        :style="{
          background: isDark ? 'rgba(59,130,246,0.16)' : 'rgba(59,130,246,0.1)',
          color: '#3b82f6',
        }"
        :disabled="scaling"
        @click="doScaleUp"
      >
        <Loader v-if="scaling" :size="10" class="animate-spin" />
        <Plus v-else :size="10" />
        扩容
      </button>
      <button
        class="ml-auto flex items-center gap-1 px-2 py-1 rounded text-[11px] cursor-pointer disabled:opacity-50"
        :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }"
        :disabled="scaling || props.busy"
        @click="releaseIdle"
      >
        <Trash2 :size="10" />
        释放 idle
      </button>
    </div>
  </div>
</template>
