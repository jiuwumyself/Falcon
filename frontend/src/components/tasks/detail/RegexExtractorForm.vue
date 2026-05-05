<script setup lang="ts">
import { reactive, watch } from 'vue'
import type { RegexExtractorDetail } from '@/types/task'

const props = defineProps<{ detail: RegexExtractorDetail; isDark: boolean }>()
const emit = defineEmits<{ (e: 'update:detail', next: RegexExtractorDetail): void }>()

const local = reactive<RegexExtractorDetail>({ ...props.detail })

watch(() => props.detail, (d) => Object.assign(local, d))
watch(local, () => emit('update:detail', { ...local }), { deep: true })

const inputStyle = (isDark: boolean) => ({
  background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
  border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
  color: isDark ? '#fff' : '#1a1a2e',
})
const labelColor = (isDark: boolean) => ({
  color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)',
})
</script>

<template>
  <div class="flex flex-col gap-4">
    <div v-for="f in [
      { key: 'refname', label: '引用名称（变量名）', placeholder: 'token' },
      { key: 'regex', label: '正则表达式', placeholder: 'token=(.+?)&' },
      { key: 'template', label: '模板', placeholder: '$1$' },
      { key: 'default', label: '默认值', placeholder: '' },
      { key: 'matchNumber', label: '匹配序号（-1=随机，0=全部，N=第N个）', placeholder: '1' },
    ]" :key="f.key" class="flex flex-col gap-1">
      <label class="text-[11px]" :style="labelColor(isDark)">{{ f.label }}</label>
      <input
        v-model="(local as Record<string, string>)[f.key]"
        type="text"
        :placeholder="f.placeholder"
        class="px-2.5 py-1.5 rounded-md text-[12px] font-mono outline-none"
        :style="inputStyle(isDark)"
      />
    </div>

    <div class="flex flex-col gap-1">
      <label class="text-[11px]" :style="labelColor(isDark)">提取范围</label>
      <select
        v-model="local.useHeaders"
        class="px-2.5 py-1.5 rounded-md text-[12px] outline-none"
        :style="inputStyle(isDark)"
      >
        <option value="false">响应体</option>
        <option value="true">响应头</option>
        <option value="request">请求头</option>
        <option value="URL">URL</option>
        <option value="response_code">响应码</option>
        <option value="response_message">响应消息</option>
      </select>
    </div>
  </div>
</template>
