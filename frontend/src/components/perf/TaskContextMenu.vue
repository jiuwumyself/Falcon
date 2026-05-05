<script setup lang="ts">
import { onMounted, onBeforeUnmount, computed } from 'vue'
import { Motion } from 'motion-v'
import { Trash2 } from 'lucide-vue-next'

const props = defineProps<{
  x: number
  y: number
  isDark: boolean
  visible: boolean
}>()

const emit = defineEmits<{
  (e: 'delete'): void
  (e: 'close'): void
}>()

// Clamp menu inside viewport so corner clicks don't push it off-screen.
const positionStyle = computed(() => {
  const w = 140
  const h = 40
  const padding = 8
  const maxX = window.innerWidth - w - padding
  const maxY = window.innerHeight - h - padding
  return {
    left: `${Math.min(props.x, maxX)}px`,
    top: `${Math.min(props.y, maxY)}px`,
  }
})

function onDocClick() { emit('close') }
function onEsc(e: KeyboardEvent) { if (e.key === 'Escape') emit('close') }

onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('contextmenu', onDocClick)
  document.addEventListener('keydown', onEsc)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('contextmenu', onDocClick)
  document.removeEventListener('keydown', onEsc)
})
</script>

<template>
  <Motion
    v-if="visible"
    :initial="{ opacity: 0, scale: 0.96 }"
    :animate="{ opacity: 1, scale: 1 }"
    :transition="{ duration: 0.12 }"
    class="fixed z-[100] rounded-lg overflow-hidden"
    :style="{
      ...positionStyle,
      width: '140px',
      background: isDark ? 'rgba(20,20,20,0.95)' : 'rgba(255,255,255,0.97)',
      backdropFilter: 'blur(20px)',
      border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
      boxShadow: '0 8px 24px rgba(0,0,0,0.18)',
    }"
    @click.stop
    @contextmenu.stop.prevent
  >
    <button
      class="w-full flex items-center gap-2 px-3 py-2 text-[12px] cursor-pointer transition-colors"
      :style="{ color: '#ef4444' }"
      @mouseenter="(e: MouseEvent) => ((e.currentTarget as HTMLElement).style.background = isDark ? 'rgba(239,68,68,0.12)' : 'rgba(239,68,68,0.08)')"
      @mouseleave="(e: MouseEvent) => ((e.currentTarget as HTMLElement).style.background = 'transparent')"
      @click="emit('delete')"
    >
      <Trash2 :size="13" />
      <span>删除任务</span>
    </button>
  </Motion>
</template>
