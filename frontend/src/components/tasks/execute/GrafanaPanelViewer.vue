<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, ExternalLink } from 'lucide-vue-next'
import type { GrafanaPanel } from '@/types/task'

const props = defineProps<{
  panels: GrafanaPanel[]
  // run 时间窗（毫秒），iframe url 自动追加 ?from=...&to=...
  fromMs: number | null
  toMs: number | null
  isDark: boolean
}>()

const currentIndex = ref(0)

watch(() => props.panels, () => { currentIndex.value = 0 })

const currentPanel = computed(() => props.panels[currentIndex.value] ?? null)

// 把时间窗作为 query 参数追加到 panel.url；Grafana 用 from / to 毫秒时间戳
const iframeSrc = computed(() => {
  const p = currentPanel.value
  if (!p) return ''
  const sep = p.url.includes('?') ? '&' : '?'
  const parts: string[] = []
  if (props.fromMs) parts.push(`from=${props.fromMs}`)
  if (props.toMs) parts.push(`to=${props.toMs}`)
  return parts.length ? `${p.url}${sep}${parts.join('&')}` : p.url
})

function prev() {
  if (currentIndex.value > 0) currentIndex.value -= 1
}
function next() {
  if (currentIndex.value < props.panels.length - 1) currentIndex.value += 1
}
function jump(i: number) {
  if (i >= 0 && i < props.panels.length) currentIndex.value = i
}
</script>

<template>
  <div v-if="panels.length" class="flex flex-col gap-2">
    <!-- 按钮组（panel 名快速切换） -->
    <div class="flex items-center gap-1.5 flex-wrap">
      <button
        v-for="(p, i) in panels"
        :key="p.name + i"
        class="px-2 py-1 rounded text-[11px] cursor-pointer"
        :style="{
          background: i === currentIndex
            ? (isDark ? 'rgba(59,130,246,0.2)' : 'rgba(59,130,246,0.12)')
            : (isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)'),
          color: i === currentIndex
            ? (isDark ? '#93c5fd' : '#2563eb')
            : (isDark ? 'rgba(255,255,255,0.65)' : 'rgba(0,0,0,0.7)'),
          border: `1px solid ${i === currentIndex
            ? (isDark ? 'rgba(59,130,246,0.35)' : 'rgba(59,130,246,0.3)')
            : 'transparent'}`,
        }"
        @click="jump(i)"
      >{{ p.name }}</button>
    </div>

    <!-- iframe + 分页器 -->
    <div
      class="rounded-lg overflow-hidden"
      :style="{
        background: isDark ? '#0a0a0a' : '#fafafa',
        border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)'}`,
      }"
    >
      <iframe
        v-if="iframeSrc"
        :src="iframeSrc"
        :style="{
          width: '100%', height: '420px', border: '0',
          background: isDark ? '#0a0a0a' : '#fff',
        }"
        loading="lazy"
        sandbox="allow-scripts allow-same-origin allow-popups"
      />
      <div class="flex items-center px-3 py-1.5 gap-2"
           :style="{
             borderTop: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
           }">
        <button
          class="flex items-center justify-center w-6 h-6 rounded cursor-pointer disabled:opacity-30"
          :style="{ color: isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.6)' }"
          :disabled="currentIndex === 0"
          @click="prev"
        ><ChevronLeft :size="13" /></button>
        <span class="text-[11px]"
              :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }">
          {{ currentIndex + 1 }} / {{ panels.length }} · {{ currentPanel?.name }}
        </span>
        <button
          class="flex items-center justify-center w-6 h-6 rounded cursor-pointer disabled:opacity-30"
          :style="{ color: isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.6)' }"
          :disabled="currentIndex === panels.length - 1"
          @click="next"
        ><ChevronRight :size="13" /></button>
        <a
          v-if="currentPanel"
          :href="iframeSrc"
          target="_blank"
          class="ml-auto flex items-center gap-1 text-[10px] cursor-pointer hover:underline"
          :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.5)' }"
        >
          <ExternalLink :size="10" />
          新窗口打开
        </a>
      </div>
    </div>
  </div>
</template>
