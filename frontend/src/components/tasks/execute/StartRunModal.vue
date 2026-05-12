<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  X, Plus, RefreshCw, Loader, AlertCircle, AlertTriangle, CheckCircle2, Server, Play,
} from 'lucide-vue-next'
import { ApiError, loadGeneratorsApi } from '@/lib/api'
import type { LoadGenerator } from '@/types/task'

const props = defineProps<{
  open: boolean
  vusers: number
  // 多 TG + 多 agent 时 jmx 缩放可能让总线程数偏差 ±N（N=TG 数）。这是 v1.2 已知问题
  // （`_scale_thread_groups_to_shard` per-TG ceil 累加，详见 plan v1.2）。本轮 v1.3 仅前端
  // 警告，不动 jmx 生成逻辑。
  tgCount: number
  isDark: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'confirm', loadGeneratorIds: number[]): void
}>()

const lgs = ref<LoadGenerator[]>([])
const selectedIds = ref<Set<number>>(new Set())
const loading = ref(false)
const scaling = ref(false)
const scaleCount = ref(1)
const error = ref('')

const selected = computed(() => selectedIds.value)
const totalCapacity = computed(() =>
  lgs.value
    .filter((g) => selected.value.has(g.id))
    .reduce((sum, g) => sum + g.max_vusers, 0),
)
const recommended = computed(() => Math.max(1, Math.ceil(props.vusers / 100)))
const capacityOk = computed(() => totalCapacity.value >= props.vusers)
const canConfirm = computed(() => !loading.value && !scaling.value)
// 0 选 = 主控本机直跑（LOCAL_FALLBACK），用于开发态 / 没拉 agent 容器时
const localOnly = computed(() => selected.value.size === 0)

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    lgs.value = await loadGeneratorsApi.list()
    autoSelectIfEmpty()
  } catch (e) {
    error.value = e instanceof ApiError ? e.humanMessage : String(e)
  } finally {
    loading.value = false
  }
}

function autoSelectIfEmpty() {
  if (selectedIds.value.size > 0) return
  const idle = lgs.value
    .filter((g) => g.status === 'idle')
    .sort((a, b) => b.max_vusers - a.max_vusers)
  let need = props.vusers
  const next = new Set<number>()
  for (const g of idle) {
    if (need <= 0) break
    next.add(g.id)
    need -= g.max_vusers
  }
  // 至少选 1 台（即使 vusers 已经被前面填满也保证默认有选）
  if (next.size === 0 && idle.length) {
    next.add(idle[0].id)
  }
  selectedIds.value = next
}

function toggle(id: number) {
  const set = new Set(selectedIds.value)
  if (set.has(id)) set.delete(id)
  else set.add(id)
  selectedIds.value = set
}

async function doScaleUp() {
  if (scaling.value || scaleCount.value < 1) return
  scaling.value = true
  error.value = ''
  try {
    await loadGeneratorsApi.scaleUp(scaleCount.value)
    setTimeout(refresh, 6000)
    setTimeout(refresh, 14000)
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

function confirm() {
  if (!canConfirm.value) return
  emit('confirm', Array.from(selectedIds.value))
}

// open 状态变化时重新拉一次（保证每次开都是最新数据）
watch(() => props.open, (next) => {
  if (next) {
    selectedIds.value = new Set()
    refresh()
  }
})

// Esc 关闭
function onKey(e: KeyboardEvent) {
  if (props.open && e.key === 'Escape') emit('close')
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center"
    :style="{ background: 'rgba(0,0,0,0.6)' }"
    @click.self="emit('close')"
  >
    <div
      class="rounded-2xl p-4 w-[520px] max-w-[90vw] max-h-[85vh] flex flex-col"
      :style="{
        background: isDark ? '#0d0d12' : '#ffffff',
        border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
        boxShadow: '0 20px 60px rgba(0,0,0,0.4)',
      }"
    >
      <!-- 头部 -->
      <div class="flex items-center gap-2 mb-3">
        <Server :size="14" color="#3b82f6" />
        <span class="text-[14px]" :style="{ color: isDark ? '#fff' : '#1a1a2e' }">
          选择压力源
        </span>
        <button
          class="ml-auto flex items-center gap-1 text-[10px] cursor-pointer disabled:opacity-50"
          :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }"
          :disabled="loading"
          @click="refresh"
        >
          <Loader v-if="loading" :size="10" class="animate-spin" />
          <RefreshCw v-else :size="10" />
          刷新
        </button>
        <button
          class="flex items-center justify-center w-6 h-6 rounded cursor-pointer hover:bg-black/10"
          @click="emit('close')"
        >
          <X :size="14" :color="isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.6)'" />
        </button>
      </div>

      <!-- 容量摘要 -->
      <p class="text-[11px] mb-2"
         :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }">
        并发 <span :style="{ color: isDark ? '#fff' : '#1a1a2e' }">{{ vusers }}</span>
        <template v-if="!localOnly">
          · 建议 ≥{{ recommended }} 台 · 已选容量
          <span :style="{ color: capacityOk ? '#10b981' : '#f59e0b' }">{{ totalCapacity }}</span>
          / {{ vusers }}
        </template>
        <template v-else>
          · <span :style="{ color: '#3b82f6' }">本机直跑</span>（未选 agent，主控本机 spawn JMeter）
        </template>
      </p>

      <p v-if="error" class="text-[11px] text-red-500 flex items-center gap-1 mb-2">
        <AlertCircle :size="11" /> {{ error }}
      </p>

      <!-- agent 列表 -->
      <div class="flex-1 min-h-0 overflow-y-auto rounded-lg border"
           :style="{ borderColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' }">
        <p v-if="!lgs.length && !loading"
           class="text-[11px] py-4 text-center"
           :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">
          暂无压力源。点下方「+扩容」拉起 agent 容器。
        </p>
        <button
          v-for="g in lgs"
          :key="g.id"
          class="w-full flex items-center gap-2 px-3 py-2 text-left text-[12px] cursor-pointer disabled:opacity-50"
          :disabled="g.status !== 'idle'"
          :style="{
            background: selected.has(g.id)
              ? (isDark ? 'rgba(59,130,246,0.12)' : 'rgba(59,130,246,0.08)')
              : 'transparent',
            color: isDark ? '#fff' : '#1a1a2e',
            cursor: g.status !== 'idle' ? 'not-allowed' : 'pointer',
          }"
          @click="g.status === 'idle' && toggle(g.id)"
        >
          <span
            class="flex items-center justify-center w-4 h-4 rounded-sm flex-shrink-0"
            :style="{
              background: selected.has(g.id) ? '#3b82f6' : 'transparent',
              border: `1px solid ${selected.has(g.id)
                ? '#3b82f6'
                : (isDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.25)')}`,
            }"
          >
            <CheckCircle2 v-if="selected.has(g.id)" :size="11" color="#fff" />
          </span>
          <span class="flex-1 truncate">{{ g.pod_name }}</span>
          <span class="text-[10px]"
                :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.5)' }">
            {{ g.cpu_cores }}C/{{ g.memory_gb }}G
          </span>
          <span class="text-[10px]"
                :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.5)' }">
            cap {{ g.max_vusers }}
          </span>
          <span class="text-[10px] px-1.5 py-0.5 rounded flex-shrink-0"
                :style="{
                  background: `${statusColor(g.status)}1f`,
                  color: statusColor(g.status),
                }">
            {{ g.status }}
          </span>
        </button>
      </div>

      <!-- 扩容控件 -->
      <div class="flex items-center gap-1.5 mt-3 pt-3"
           :style="{
             borderTop: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
           }">
        <input
          v-model.number="scaleCount"
          type="number"
          min="1"
          max="20"
          class="w-12 px-1.5 py-1 rounded text-[11px] text-center outline-none"
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
          扩容 {{ scaleCount }} 台
        </button>
        <span class="text-[10px] ml-2"
              :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.45)' }">
          扩容后 ~10s agent 自动 register
        </span>
      </div>

      <!-- 多 TG + 多压力源 警告：jmx 缩放每个 TG 各自 ceil 累加，总线程数会有 ±N 误差 -->
      <div
        v-if="tgCount > 1 && selected.size > 1"
        class="flex items-start gap-2 mt-3 p-2 rounded text-[11.5px]"
        :style="{
          background: isDark ? 'rgba(245,158,11,0.08)' : 'rgba(245,158,11,0.1)',
          color: '#f59e0b',
          border: '1px solid rgba(245,158,11,0.25)',
        }"
      >
        <AlertTriangle :size="13" class="mt-0.5 flex-shrink-0" />
        <span>
          多线程组 ({{ tgCount }}) + 多压力源 ({{ selected.size }})：每个 TG 在每台压力源
          上按比例缩放 + 向上取整，实际总线程数可能与配置有 ±{{ tgCount }} 误差。需要
          <b>精确</b>总并发请用单机模式（选 1 台）。
        </span>
      </div>

      <!-- 底部按钮 -->
      <div class="flex items-center gap-2 mt-3 justify-end">
        <button
          class="px-3 py-1.5 rounded-lg text-[12px] cursor-pointer"
          :style="{
            background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)',
            color: isDark ? 'rgba(255,255,255,0.75)' : 'rgba(0,0,0,0.7)',
          }"
          @click="emit('close')"
        >取消</button>
        <button
          class="flex items-center gap-1 px-3 py-1.5 rounded-lg text-[12px] cursor-pointer disabled:opacity-40"
          :style="{ background: localOnly ? '#3b82f6' : '#10b981', color: '#fff' }"
          :disabled="!canConfirm"
          @click="confirm"
          :title="tgCount > 1 && selected.size > 1
            ? `多 TG (${tgCount}) + 多压力源 (${selected.size}) 分配按比例缩放，实际总线程数可能与配置有 ±${tgCount} 误差；要精确总并发请用单机模式`
            : ''"
        >
          <Play :size="11" />
          {{ localOnly ? '本机直跑' : '确认并开始' }}
        </button>
      </div>
    </div>
  </div>
</template>
