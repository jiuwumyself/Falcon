<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import type { HttpDefaultsDetail } from '@/types/task'

const props = defineProps<{ detail: HttpDefaultsDetail; isDark: boolean }>()
const emit = defineEmits<{ (e: 'update:detail', next: HttpDefaultsDetail): void }>()

const activeTab = ref<'basic' | 'advanced'>('basic')

const local = reactive<HttpDefaultsDetail>({ ...props.detail })

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
    <!-- Tabs -->
    <div class="flex gap-1">
      <button
        v-for="tab in [{ id: 'basic', label: '基本' }, { id: 'advanced', label: '高级' }]"
        :key="tab.id"
        class="px-3 py-1 rounded-md text-[12px] cursor-pointer transition-colors"
        :style="{
          background: activeTab === tab.id
            ? isDark ? 'rgba(59,130,246,0.2)' : 'rgba(59,130,246,0.12)'
            : isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)',
          color: activeTab === tab.id ? '#3b82f6' : isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.6)',
          border: `1px solid ${activeTab === tab.id ? 'rgba(59,130,246,0.3)' : isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
        }"
        @click="activeTab = tab.id as 'basic' | 'advanced'"
      >{{ tab.label }}</button>
    </div>

    <!-- Basic tab -->
    <template v-if="activeTab === 'basic'">
      <div v-for="f in [
        { key: 'domain', label: '服务器名称或 IP', placeholder: 'example.com' },
        { key: 'port', label: '端口号', placeholder: '80' },
        { key: 'protocol', label: '协议', placeholder: 'https' },
        { key: 'path', label: '路径', placeholder: '/api' },
        { key: 'contentEncoding', label: '内容编码', placeholder: 'UTF-8' },
      ]" :key="f.key" class="flex flex-col gap-1">
        <label class="text-[11px]" :style="labelColor(isDark)">{{ f.label }}</label>
        <input
          v-model="(local as Record<string, string | boolean>)[f.key]"
          type="text"
          :placeholder="f.placeholder"
          class="px-2.5 py-1.5 rounded-md text-[12px] outline-none"
          :style="inputStyle(isDark)"
        />
      </div>
    </template>

    <!-- Advanced tab -->
    <template v-else>
      <div v-for="f in [
        { key: 'connectTimeout', label: '连接超时（毫秒）', placeholder: '5000' },
        { key: 'responseTimeout', label: '响应超时（毫秒）', placeholder: '10000' },
        { key: 'implementation', label: '实现', placeholder: 'HttpClient4' },
      ]" :key="f.key" class="flex flex-col gap-1">
        <label class="text-[11px]" :style="labelColor(isDark)">{{ f.label }}</label>
        <input
          v-model="(local as Record<string, string | boolean>)[f.key]"
          type="text"
          :placeholder="f.placeholder"
          class="px-2.5 py-1.5 rounded-md text-[12px] outline-none"
          :style="inputStyle(isDark)"
        />
      </div>

      <div v-for="f in [
        { key: 'followRedirects', label: '跟随重定向' },
        { key: 'useKeepAlive', label: '使用 Keep-Alive' },
      ]" :key="f.key" class="flex items-center gap-2">
        <input
          type="checkbox"
          :checked="(local as Record<string, string | boolean>)[f.key] as boolean"
          @change="(local as Record<string, string | boolean>)[f.key] = ($event.target as HTMLInputElement).checked"
        />
        <label class="text-[12px] cursor-pointer" :style="{ color: isDark ? 'rgba(255,255,255,0.8)' : 'rgba(0,0,0,0.8)' }">
          {{ f.label }}
        </label>
      </div>
    </template>
  </div>
</template>
