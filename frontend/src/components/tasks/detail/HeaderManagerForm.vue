<script setup lang="ts">
import { reactive, watch } from 'vue'
import { Plus, Trash2 } from 'lucide-vue-next'
import type { HeaderManagerDetail } from '@/types/task'

const props = defineProps<{ detail: HeaderManagerDetail; isDark: boolean }>()
const emit = defineEmits<{ (e: 'update:detail', next: HeaderManagerDetail): void }>()

const local = reactive<HeaderManagerDetail>({
  kind: 'HeaderManager',
  headers: props.detail.headers.map((h) => ({ ...h })),
})

watch(
  () => props.detail,
  (d) => {
    local.headers = d.headers.map((h) => ({ ...h }))
  },
)
watch(local, () => emit('update:detail', {
  kind: 'HeaderManager',
  headers: local.headers.map((h) => ({ ...h })),
}), { deep: true })

function addHeader() {
  local.headers.push({ name: '', value: '' })
}
function removeHeader(i: number) {
  local.headers.splice(i, 1)
}
</script>

<template>
  <div class="flex flex-col gap-2">
    <label
      class="text-[10px] uppercase tracking-wider mb-1"
      :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
    >Headers ({{ local.headers.length }})</label>

    <div
      v-for="(h, i) in local.headers"
      :key="i"
      class="flex items-center gap-2"
    >
      <input
        v-model="h.name"
        type="text"
        placeholder="Header-Name"
        class="flex-1 px-2.5 py-1.5 rounded-md text-[12px] font-mono outline-none"
        :style="{
          background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
          border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
          color: isDark ? '#fff' : '#1a1a2e',
        }"
      />
      <input
        v-model="h.value"
        type="text"
        placeholder="value"
        class="flex-[2] px-2.5 py-1.5 rounded-md text-[12px] font-mono outline-none"
        :style="{
          background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
          border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
          color: isDark ? '#fff' : '#1a1a2e',
        }"
      />
      <button
        class="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0 cursor-pointer"
        :style="{
          background: isDark ? 'rgba(239,68,68,0.1)' : 'rgba(239,68,68,0.08)',
          color: '#ef4444',
          border: `1px solid ${isDark ? 'rgba(239,68,68,0.2)' : 'rgba(239,68,68,0.18)'}`,
        }"
        @click="removeHeader(i)"
      >
        <Trash2 :size="12" />
      </button>
    </div>

    <button
      class="px-3 py-2 rounded-md text-[12px] flex items-center justify-center gap-1.5 mt-1 cursor-pointer"
      :style="{
        background: isDark ? 'rgba(59,130,246,0.08)' : 'rgba(59,130,246,0.06)',
        color: '#3b82f6',
        border: `1px dashed ${isDark ? 'rgba(59,130,246,0.3)' : 'rgba(59,130,246,0.3)'}`,
      }"
      @click="addHeader"
    >
      <Plus :size="12" />
      添加 header
    </button>
  </div>
</template>
