<script setup lang="ts">
import { ref } from 'vue'

// 自定义 hover 提示气泡（替代 native :title=，秒显 + 多行靠 white-space: pre-line）。
// 用法：
//   <HoverTip :tip="'第一行\n第二行'" :is-dark="isDark">
//     <span>标题文字</span>
//   </HoverTip>
defineProps<{
  tip: string
  isDark: boolean
}>()

const show = ref(false)
</script>

<template>
  <span
    class="relative inline-block cursor-help"
    @mouseenter="show = true"
    @mouseleave="show = false"
  >
    <slot />
    <span
      v-if="show && tip"
      class="absolute z-50 left-0 top-full mt-1 px-3 py-2 rounded-lg text-[11.5px] leading-[1.6] whitespace-pre-line shadow-lg"
      :style="{
        background: isDark ? 'rgba(20,20,22,0.96)' : 'rgba(255,255,255,0.98)',
        border: isDark ? '1px solid rgba(255,255,255,0.1)' : '1px solid rgba(0,0,0,0.08)',
        color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.85)',
        maxWidth: '380px',
        minWidth: '260px',
        pointerEvents: 'none',
      }"
    >{{ tip }}</span>
  </span>
</template>
