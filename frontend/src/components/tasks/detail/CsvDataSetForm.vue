<script setup lang="ts">
import { reactive, watch } from 'vue'
import type { CsvDataSetDetail } from '@/types/task'

const props = defineProps<{ detail: CsvDataSetDetail; isDark: boolean }>()
const emit = defineEmits<{ (e: 'update:detail', next: CsvDataSetDetail): void }>()

const local = reactive<CsvDataSetDetail>({ ...props.detail })

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
    <!-- Filename notice -->
    <p
      class="text-[11px] rounded-md px-3 py-2"
      :style="{
        color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)',
        background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.025)',
        border: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
      }"
    >
      文件通过组件树行内 📎 上传按钮管理，此处不显示文件名路径。
    </p>

    <div class="flex flex-col gap-1">
      <label class="text-[11px]" :style="labelColor(isDark)">变量名（逗号分隔）</label>
      <input
        v-model="local.variableNames"
        type="text"
        placeholder="username,password"
        class="px-2.5 py-1.5 rounded-md text-[12px] font-mono outline-none"
        :style="inputStyle(isDark)"
      />
    </div>

    <div class="flex flex-col gap-1">
      <label class="text-[11px]" :style="labelColor(isDark)">分隔符</label>
      <input
        v-model="local.delimiter"
        type="text"
        placeholder=","
        class="px-2.5 py-1.5 rounded-md text-[12px] font-mono outline-none w-24"
        :style="inputStyle(isDark)"
      />
    </div>

    <div class="flex flex-col gap-1">
      <label class="text-[11px]" :style="labelColor(isDark)">文件编码</label>
      <input
        v-model="local.fileEncoding"
        type="text"
        placeholder="UTF-8"
        class="px-2.5 py-1.5 rounded-md text-[12px] outline-none w-36"
        :style="inputStyle(isDark)"
      />
    </div>

    <div class="flex flex-col gap-1">
      <label class="text-[11px]" :style="labelColor(isDark)">共享模式</label>
      <select
        v-model="local.shareMode"
        class="px-2.5 py-1.5 rounded-md text-[12px] outline-none"
        :style="inputStyle(isDark)"
      >
        <option value="shareMode.all">全部线程</option>
        <option value="shareMode.group">当前线程组</option>
        <option value="shareMode.thread">当前线程</option>
      </select>
    </div>

    <div class="flex flex-col gap-2">
      <label class="text-[11px]" :style="labelColor(isDark)">选项</label>
      <div
        v-for="f in [
          { key: 'ignoreFirstLine', label: '忽略第一行（列名行）' },
          { key: 'quotedData', label: '允许引号内含分隔符' },
          { key: 'recycle', label: '文件结尾后循环' },
          { key: 'stopThread', label: '文件结尾后停止线程' },
        ]"
        :key="f.key"
        class="flex items-center gap-2"
      >
        <input
          type="checkbox"
          :checked="(local as Record<string, string | boolean>)[f.key] as boolean"
          @change="(local as Record<string, string | boolean>)[f.key] = ($event.target as HTMLInputElement).checked"
        />
        <label class="text-[12px]" :style="{ color: isDark ? 'rgba(255,255,255,0.8)' : 'rgba(0,0,0,0.8)' }">{{ f.label }}</label>
      </div>
    </div>
  </div>
</template>
