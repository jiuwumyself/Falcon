<script setup lang="ts">
import { computed, ref, nextTick, onBeforeUnmount, watch } from 'vue'
import { Server, Plus, X, Search, Info, Check, Database } from 'lucide-vue-next'
import { prometheusSourcesApi } from '@/lib/api'
import type { PrometheusDataSource } from '@/types/task'

const props = defineProps<{
  modelValue: string[]       // 已选的 service name 列表
  sourceId: number | null    // 已选的 Prometheus 数据源 ID
  isDark: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: string[]): void
  (e: 'update:sourceId', v: number | null): void
}>()

// ── Prometheus 数据源 + 服务发现 ──
const sources = ref<PrometheusDataSource[]>([])
const sourcesLoading = ref(false)
const selectedSourceId = ref<number | null>(props.sourceId)
const prometheusServices = ref<string[]>([])
const servicesLoading = ref(false)

// 初始化：拉数据源列表
;(async () => {
  sourcesLoading.value = true
  try {
    sources.value = await prometheusSourcesApi.list()
    // 自动选第一个（如果 props.sourceId 为空）
    if (sources.value.length && !selectedSourceId.value) {
      selectedSourceId.value = sources.value[0].id
    }
  } catch {
    // 数据源不可达 → services 留空
  } finally {
    sourcesLoading.value = false
  }
})()

// 数据源切换时拉服务列表 + 通知父组件
watch(selectedSourceId, async (id) => {
  emit('update:sourceId', id)
  if (!id) {
    prometheusServices.value = []
    return
  }
  servicesLoading.value = true
  try {
    const r = await prometheusSourcesApi.services(id)
    prometheusServices.value = r.services
  } catch {
    prometheusServices.value = []
  } finally {
    servicesLoading.value = false
  }
})

const open = ref(false)
const query = ref('')
const searchInput = ref<HTMLInputElement | null>(null)
const wrapper = ref<HTMLElement | null>(null)

const selected = computed(() => new Set(props.modelValue))

// 候选过滤：按名字模糊匹配（大小写不敏感）
const candidates = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return prometheusServices.value
  return prometheusServices.value.filter((name) => name.toLowerCase().includes(q))
})

function toggle(name: string) {
  const set = new Set(props.modelValue)
  if (set.has(name)) set.delete(name)
  else set.add(name)
  emit('update:modelValue', Array.from(set))
}

function remove(name: string) {
  emit('update:modelValue', props.modelValue.filter((n) => n !== name))
}

async function openDropdown() {
  open.value = true
  await nextTick()
  searchInput.value?.focus()
}

function closeDropdown() {
  open.value = false
  query.value = ''
}

// 点击 wrapper 外面 → 关闭
function onDocClick(e: MouseEvent) {
  if (!open.value) return
  if (wrapper.value && !wrapper.value.contains(e.target as Node)) {
    closeDropdown()
  }
}
document.addEventListener('mousedown', onDocClick)
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocClick))
</script>

<template>
  <div ref="wrapper" class="relative">
    <!-- 数据源选择器 -->
    <div class="flex items-center gap-1.5 mb-1.5">
      <Database
        :size="11"
        :color="isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.45)'"
      />
      <select
        v-model="selectedSourceId"
        class="text-[11px] rounded px-1.5 py-0.5 outline-none"
        :style="{
          background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)',
          color: isDark ? '#fff' : '#1a1a2e',
          border: `1px solid ${isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)'}`,
        }"
      >
        <option v-if="sourcesLoading" :value="null">加载中…</option>
        <option v-else-if="!sources.length" :value="null">未配置数据源</option>
        <option
          v-for="src in sources"
          :key="src.id"
          :value="src.id"
        >{{ src.name }}</option>
      </select>
      <span
        v-if="servicesLoading"
        class="text-[10px]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
      >加载服务…</span>
    </div>

    <!-- chips 容器 + 添加按钮 -->
    <div
      class="flex flex-wrap items-center gap-1.5 p-1.5 rounded-lg min-h-[34px]"
      :style="{
        background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
        border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
      }"
    >
      <Server
        :size="12"
        :color="isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.45)'"
        class="ml-1"
      />

      <!-- 已选 chips -->
      <span
        v-for="name in modelValue"
        :key="name"
        class="inline-flex items-center gap-1 pl-2 pr-1 py-0.5 rounded-md text-[11px]"
        :style="{
          background: isDark ? 'rgba(59,130,246,0.16)' : 'rgba(59,130,246,0.1)',
          color: isDark ? '#93c5fd' : '#2563eb',
          border: `1px solid ${isDark ? 'rgba(59,130,246,0.28)' : 'rgba(59,130,246,0.22)'}`,
        }"
      >
        {{ name }}
        <button
          class="flex items-center justify-center w-3.5 h-3.5 rounded cursor-pointer hover:bg-black/10"
          :title="`移除 ${name}`"
          @click="remove(name)"
        >
          <X :size="10" />
        </button>
      </span>

      <!-- 添加按钮 / 占位提示 -->
      <button
        v-if="!modelValue.length"
        class="flex items-center gap-1 text-[11px] px-2 py-0.5 cursor-pointer"
        :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.45)' }"
        @click="openDropdown"
      >
        <Plus :size="11" />
        选择服务（可多选）
      </button>
      <button
        v-else
        class="flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded cursor-pointer"
        :style="{
          color: isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.55)',
          background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
        }"
        title="添加更多服务"
        @click="openDropdown"
      >
        <Plus :size="11" />
        添加
      </button>
    </div>

    <!-- 下拉：搜索 + 候选列表 -->
    <div
      v-if="open"
      class="absolute top-full left-0 mt-1 w-[320px] rounded-lg z-30 py-1"
      :style="{
        background: isDark ? '#111116' : '#ffffff',
        border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
        boxShadow: '0 8px 30px rgba(0,0,0,0.18)',
      }"
    >
      <!-- 搜索框 -->
      <div
        class="flex items-center gap-1.5 px-2.5 py-1.5 mx-1.5 mt-1 rounded"
        :style="{
          background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)',
        }"
      >
        <Search :size="12" :color="isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)'" />
        <input
          ref="searchInput"
          v-model="query"
          placeholder="搜索服务名…"
          class="flex-1 bg-transparent outline-none text-[12px]"
          :style="{ color: isDark ? '#fff' : '#1a1a2e' }"
          @keydown.escape="closeDropdown"
        />
        <button
          v-if="query"
          class="text-[10px] cursor-pointer px-1"
          :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
          @click="query = ''"
        >清空</button>
      </div>

      <!-- 候选列表 -->
      <div class="max-h-[280px] overflow-y-auto mt-1">
        <p
          v-if="!candidates.length"
          class="px-3 py-3 text-[11px] text-center"
          :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
        >无匹配服务</p>

        <button
          v-for="name in candidates"
          :key="name"
          class="w-full flex items-start gap-2 px-3 py-1.5 text-[12px] cursor-pointer hover:bg-black/5"
          :style="{
            color: selected.has(name)
              ? (isDark ? '#93c5fd' : '#2563eb')
              : (isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)'),
          }"
          @click="toggle(name)"
        >
          <span
            class="mt-0.5 flex items-center justify-center w-3.5 h-3.5 rounded-sm flex-shrink-0"
            :style="{
              background: selected.has(name)
                ? '#3b82f6'
                : (isDark ? 'transparent' : 'transparent'),
              border: `1px solid ${selected.has(name)
                ? '#3b82f6'
                : (isDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.25)')}`,
            }"
          >
            <Check v-if="selected.has(name)" :size="10" color="#fff" />
          </span>
          <span class="flex-1 text-left min-w-0">
            <span class="truncate">{{ name }}</span>
          </span>
        </button>
      </div>

      <div
        class="border-t mt-1 pt-1.5 px-3 py-1.5 text-[10px] flex items-center justify-between gap-1"
        :style="{
          borderColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
          color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.4)',
        }"
      >
        <span class="flex items-center gap-1">
          <Info :size="10" />
          数据来自 Prometheus，数据源在 admin 配置
        </span>
        <span v-if="modelValue.length">已选 {{ modelValue.length }}</span>
      </div>
    </div>
  </div>
</template>
