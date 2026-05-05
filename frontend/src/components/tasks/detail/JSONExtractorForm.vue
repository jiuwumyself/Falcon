<script setup lang="ts">
import { reactive, watch } from 'vue'
import type { JSONExtractorDetail } from '@/types/task'

const props = defineProps<{ detail: JSONExtractorDetail; isDark: boolean }>()
const emit = defineEmits<{ (e: 'update:detail', next: JSONExtractorDetail): void }>()

const local = reactive<JSONExtractorDetail>({ ...props.detail })

watch(() => props.detail, (d) => Object.assign(local, d))
watch(local, () => emit('update:detail', { ...local }), { deep: true })

const inputStyle = (isDark: boolean) => ({
  background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
  border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
  color: isDark ? '#fff' : '#1a1a2e',
})
</script>

<template>
  <div class="flex flex-col gap-4">
    <div v-for="f in [
      { key: 'varName', label: '变量名', placeholder: 'token' },
      { key: 'jsonpath', label: 'JSONPath 表达式', placeholder: '$.data.token' },
      { key: 'default', label: '默认值', placeholder: '' },
      { key: 'matchNo', label: '匹配序号（-1=随机，0=全部，N=第N个）', placeholder: '1' },
    ]" :key="f.key" class="flex flex-col gap-1">
      <label class="text-[11px]" :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }">{{ f.label }}</label>
      <input
        v-model="(local as Record<string, string>)[f.key]"
        type="text"
        :placeholder="f.placeholder"
        class="px-2.5 py-1.5 rounded-md text-[12px] font-mono outline-none"
        :style="inputStyle(isDark)"
      />
    </div>
  </div>
</template>
