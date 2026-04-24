<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AnimatePresence, Motion } from 'motion-v'
import { Sun, Moon } from 'lucide-vue-next'
import { useTheme } from '@/composables/useTheme'
import FalconLogo from '@/components/FalconLogo.vue'
import GlassNav from '@/components/GlassNav.vue'

// Top-nav tabs — each maps to a peer top-level route (平级，不是嵌在 /home 下)
const NAV_ITEMS = [
  { name: 'home', path: '/home', label: '概览' },
  { name: 'performance', path: '/performance', label: '性能板块' },
  { name: 'ui', path: '/ui', label: 'UI 板块' },
  { name: 'api', path: '/api', label: '接口板块' },
]

const { theme, toggleTheme } = useTheme()
const isDark = computed(() => theme.value === 'dark')
const route = useRoute()
const router = useRouter()

// "performance-tasks" and future nested routes still light up their parent tab.
const activeTabName = computed(() => {
  const r = route.name as string | undefined
  if (!r) return 'home'
  if (r.startsWith('performance')) return 'performance'
  return r
})

const tabRefs = reactive<Record<string, HTMLButtonElement | null>>({})
const sliderStyle = reactive({ left: 0, width: 0 })
const setTabRef = (name: string) => (el: any) => { tabRefs[name] = el as HTMLButtonElement | null }

function updateSlider() {
  const el = tabRefs[activeTabName.value]
  if (el) {
    sliderStyle.left = el.offsetLeft
    sliderStyle.width = el.offsetWidth
  }
}

function handleNav(path: string) {
  router.push(path)
}

onMounted(() => { nextTick(updateSlider) })
watch(activeTabName, () => nextTick(updateSlider))
</script>

<template>
  <div
    class="h-screen overflow-hidden transition-colors duration-500 relative"
    :style="{ background: isDark ? '#0A0A0A' : '#F5F5F7' }"
  >
    <template v-if="isDark">
      <div
        class="fixed top-0 left-1/4 w-[600px] h-[600px] pointer-events-none"
        style="background: radial-gradient(ellipse, rgba(59,130,246,0.04) 0%, transparent 70%)"
      />
      <div
        class="fixed bottom-0 right-1/4 w-[500px] h-[500px] pointer-events-none"
        style="background: radial-gradient(ellipse, rgba(124,58,237,0.03) 0%, transparent 70%)"
      />
    </template>

    <!-- Command Island (top nav) -->
    <div class="fixed top-3 left-1/2 -translate-x-1/2 z-50 w-[calc(100%-40px)] max-w-[860px]">
      <GlassNav>
        <div class="flex items-center justify-between px-3 py-1.5">
          <div class="flex items-center gap-3">
            <div class="flex items-center gap-1.5 pr-3 border-r border-white/[0.06]">
              <FalconLogo :size="18" />
              <span
                class="text-[11px] tracking-tight hidden sm:block"
                :style="{ color: isDark ? '#fff' : '#1a1a2e' }"
              >Falcon Eyes</span>
            </div>
            <div
              class="relative flex rounded-full p-0.5"
              :style="{ background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)' }"
            >
              <Motion
                class="absolute top-0.5 h-[calc(100%-4px)] rounded-full"
                :animate="{ left: sliderStyle.left, width: sliderStyle.width }"
                :transition="{ type: 'spring', stiffness: 400, damping: 30 }"
                :style="{
                  background: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(255,255,255,0.8)',
                  boxShadow: isDark ? '0 2px 8px rgba(0,0,0,0.2)' : '0 2px 8px rgba(0,0,0,0.06)',
                }"
              />
              <button
                v-for="item in NAV_ITEMS"
                :key="item.name"
                :ref="setTabRef(item.name)"
                class="relative z-10 px-3 py-0.5 rounded-full text-[11.5px] transition-colors duration-200 cursor-pointer whitespace-nowrap"
                :style="{
                  color: activeTabName === item.name
                    ? isDark ? '#fff' : '#1a1a2e'
                    : isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)',
                }"
                @click="handleNav(item.path)"
              >
                {{ item.label }}
              </button>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <Motion
              as="button"
              :while-tap="{ scale: 0.9 }"
              class="w-7 h-7 rounded-full flex items-center justify-center cursor-pointer"
              :style="{ background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)' }"
              @click="(e: MouseEvent) => toggleTheme(e)"
            >
              <AnimatePresence mode="wait">
                <Motion
                  :key="theme"
                  :initial="{ rotate: -90, opacity: 0 }"
                  :animate="{ rotate: 0, opacity: 1 }"
                  :exit="{ rotate: 90, opacity: 0 }"
                  :transition="{ duration: 0.2 }"
                >
                  <component :is="isDark ? Moon : Sun" :size="13" :color="isDark ? '#93c5fd' : '#f59e0b'" />
                </Motion>
              </AnimatePresence>
            </Motion>
            <div class="relative">
              <Motion
                class="absolute -inset-0.5 rounded-full"
                :animate="{ opacity: [0.3, 0.7, 0.3] }"
                :transition="{ duration: 3, repeat: Infinity }"
                style="background: conic-gradient(from 0deg, #3b82f6, #7c3aed, #3b82f6); filter: blur(2px)"
              />
              <div
                class="relative w-7 h-7 rounded-full flex items-center justify-center text-[10px] text-white"
                :style="{
                  background: 'linear-gradient(135deg, #3b82f6, #7c3aed)',
                  border: `1.5px solid ${isDark ? '#0A0A0A' : '#F5F5F7'}`,
                }"
              >FE</div>
            </div>
          </div>
        </div>
      </GlassNav>
    </div>

    <!-- Page -->
    <RouterView v-slot="{ Component, route: r }">
      <AnimatePresence mode="wait">
        <Motion
          :key="r.fullPath"
          class="h-full"
          :initial="{ opacity: 0 }"
          :animate="{ opacity: 1 }"
          :exit="{ opacity: 0 }"
          :transition="{ duration: 0.3 }"
        >
          <component :is="Component" />
        </Motion>
      </AnimatePresence>
    </RouterView>
  </div>
</template>
