<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Globe, ChevronDown, Settings2 } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import type { Environment } from '@/types/task'

const props = defineProps<{
  modelValue: number | null
  isDark: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: number | null): void
}>()

const envs = ref<Environment[]>([])
const loading = ref(false)
const error = ref('')
const open = ref(false)

async function load() {
  loading.value = true
  try {
    // EnvironmentViewSet 禁了分页，直接拿数组
    envs.value = await api<Environment[]>('/environments/')
    error.value = ''
    // 如果还没选 + 有默认环境 → 自动选默认
    if (props.modelValue == null) {
      const dflt = envs.value.find((e) => e.is_default)
      if (dflt) emit('update:modelValue', dflt.id)
    }
  } catch (e) {
    error.value = e instanceof ApiError ? e.humanMessage : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)

function pick(id: number | null) {
  emit('update:modelValue', id)
  open.value = false
}

function currentLabel(): string {
  if (loading.value) return '加载中…'
  if (!envs.value.length) return '(尚无环境)'
  if (props.modelValue == null) return '未选择'
  const e = envs.value.find((x) => x.id === props.modelValue)
  return e ? e.name : '未选择'
}
</script>

<template>
  <div class="relative">
    <button
      class="flex items-center gap-2 px-3 py-1.5 rounded-lg text-[12px] cursor-pointer"
      :style="{
        background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
        border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
        color: isDark ? '#fff' : '#1a1a2e',
      }"
      @click="open = !open"
    >
      <Globe :size="12" :color="isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.55)'" />
      环境：{{ currentLabel() }}
      <ChevronDown :size="12" :color="isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.4)'" />
    </button>

    <!-- dropdown -->
    <div
      v-if="open"
      class="absolute top-full left-0 mt-1 w-[260px] rounded-lg z-20 py-1"
      :style="{
        background: isDark ? '#111116' : '#ffffff',
        border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
        boxShadow: '0 8px 30px rgba(0,0,0,0.15)',
      }"
    >
      <p
        v-if="error"
        class="px-3 py-2 text-[11px] text-red-500"
      >{{ error }}</p>

      <button
        class="w-full flex items-center px-3 py-1.5 text-[12px] cursor-pointer hover:bg-black/5"
        :style="{
          color: modelValue == null
            ? (isDark ? '#fff' : '#1a1a2e')
            : (isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)'),
        }"
        @click="pick(null)"
      >(不指定环境)</button>

      <button
        v-for="e in envs"
        :key="e.id"
        class="w-full flex items-center gap-1 px-3 py-1.5 text-[12px] cursor-pointer hover:bg-black/5"
        :style="{
          color: e.id === modelValue
            ? (isDark ? '#fff' : '#1a1a2e')
            : (isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)'),
          background: e.id === modelValue
            ? (isDark ? 'rgba(139,92,246,0.12)' : 'rgba(139,92,246,0.08)')
            : 'transparent',
        }"
        @click="pick(e.id)"
      >
        <span class="flex-1 text-left truncate">{{ e.name }}</span>
        <span
          v-if="e.is_default"
          class="text-[9px] px-1.5 py-0.5 rounded"
          :style="{
            background: isDark ? 'rgba(16,185,129,0.12)' : 'rgba(16,185,129,0.1)',
            color: '#10b981',
          }"
        >默认</span>
        <span
          class="text-[10px] ml-1"
          :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)' }"
        >{{ e.host_entries.length }} hosts</span>
      </button>

      <div
        class="border-t mt-1 pt-1.5 px-3 py-1.5 text-[10px] flex items-center gap-1"
        :style="{
          borderColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
          color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.4)',
        }"
      >
        <Settings2 :size="10" />
        <a
          href="/admin/performance/environment/"
          target="_blank"
          class="underline hover:text-purple-500"
        >在 admin 里编辑环境</a>
      </div>
    </div>
  </div>
</template>
