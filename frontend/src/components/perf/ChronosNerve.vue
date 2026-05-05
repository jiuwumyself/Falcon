<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { AnimatePresence, Motion } from 'motion-v'
import { AlertTriangle, Plus } from 'lucide-vue-next'
import {
  BIZ, P99_THRESHOLD, parseTime, PEOPLE, SPRING, stColor, type Task,
} from './data'
import Anim from './Anim.vue'
import GlassSkeleton from './GlassSkeleton.vue'

const props = defineProps<{
  isDark: boolean
  tasks: Task[]
  rimColor: string
  activeBiz: string
}>()

const emit = defineEmits<{
  (e: 'focus', id: string | null): void
  (e: 'selectBiz', id: string): void
  (e: 'create'): void
  (e: 'editTask', id: string): void
  (e: 'contextTask', id: string, x: number, y: number): void
}>()

const isLoading = ref(true)

let timer: ReturnType<typeof setTimeout>
onMounted(() => { timer = setTimeout(() => { isLoading.value = false }, 1200) })
onBeforeUnmount(() => clearTimeout(timer))

const bizTasks = computed(() =>
  props.activeBiz === 'all' ? props.tasks : props.tasks.filter((t) => t.biz === props.activeBiz),
)

const allSorted = computed(() =>
  [...bizTasks.value].sort((a, b) => {
    if (a.date !== b.date) return b.date - a.date
    return parseTime(b.time) - parseTime(a.time)
  }),
)

function personByName(name: string) { return PEOPLE.find((p) => p.name === name) }
function bizById(id: string) { return BIZ.find((b) => b.id === id) }

function toggleBiz(id: string) {
  emit('selectBiz', props.activeBiz === id ? 'all' : id)
}

const bizHint = ref(false)
let bizHintTimer: ReturnType<typeof setTimeout> | null = null

function onCreateClick() {
  if (props.activeBiz === 'all') {
    bizHint.value = true
    if (bizHintTimer) clearTimeout(bizHintTimer)
    bizHintTimer = setTimeout(() => { bizHint.value = false }, 2000)
    return
  }
  emit('create')
}
</script>

<template>
  <div class="flex flex-col h-full py-5 px-3 relative" style="width: 320px">
    <!-- Biz category tabs -->
    <div class="flex flex-wrap gap-1.5 px-1 mb-3 flex-shrink-0">
      <Motion
        v-for="b in BIZ"
        :key="b.id"
        as="button"
        :while-tap="{ scale: 0.92 }"
        class="flex items-center gap-2 px-2.5 py-2 rounded-xl cursor-pointer relative overflow-hidden"
        :style="{
          background: activeBiz === b.id ? `${b.color}12` : isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)',
          border: `1px solid ${activeBiz === b.id ? `${b.color}25` : isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.04)'}`,
        }"
        :transition="{ type: 'spring', ...SPRING }"
        @click="toggleBiz(b.id)"
      >
        <component
          :is="b.icon"
          :size="14"
          :color="activeBiz === b.id ? b.color : isDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.25)'"
          class="relative z-10"
        />
        <span
          class="text-[11px] relative z-10"
          :style="{ color: activeBiz === b.id ? b.color : isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)' }"
        >{{ b.label }}</span>
        <span
          class="text-[10px] px-1.5 py-0.5 rounded-md relative z-10"
          :style="{
            background: activeBiz === b.id ? `${b.color}15` : isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)',
            color: activeBiz === b.id ? b.color : isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)',
          }"
        >{{ tasks.filter((t) => t.biz === b.id).length }}</span>
      </Motion>
    </div>

    <!-- Genesis Anchor -->
    <div class="relative z-50 flex-shrink-0 mb-1">
      <div class="flex items-start gap-3 pl-0 relative">
        <Motion
          class="absolute -inset-2 rounded-2xl pointer-events-none"
          :animate="{
            boxShadow: [
              '0 0 8px rgba(59,130,246,0.0), 0 0 20px rgba(139,92,246,0.0)',
              '0 0 12px rgba(59,130,246,0.15), 0 0 30px rgba(139,92,246,0.1)',
              '0 0 8px rgba(59,130,246,0.0), 0 0 20px rgba(139,92,246,0.0)',
            ],
          }"
          :transition="{ duration: 3, repeat: Infinity, ease: 'easeInOut' }"
        />

        <Motion
          :while-hover="{ scale: 1.15, boxShadow: '0 0 30px rgba(59,130,246,0.4)' }"
          :while-tap="{ scale: 0.9 }"
          class="w-[44px] h-[44px] rounded-full flex items-center justify-center cursor-pointer relative z-10 flex-shrink-0"
          :style="{
            background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)',
            boxShadow: '0 4px 20px rgba(59,130,246,0.35), inset 0 1px 0 rgba(255,255,255,0.2), inset 0 -1px 0 rgba(0,0,0,0.2)',
            opacity: activeBiz === 'all' ? 0.45 : 1,
          }"
          :transition="{ type: 'spring', ...SPRING }"
          @click="onCreateClick()"
        >
          <Plus :size="20" color="#fff" />
          <div
            class="absolute top-[4px] left-[7px] w-[14px] h-[7px] rounded-full"
            style="background: rgba(255,255,255,0.25); filter: blur(2px)"
          />
        </Motion>
        <div class="pt-1.5 flex-1">
          <p
            class="text-[14px]"
            :style="{ color: isDark ? 'rgba(255,255,255,0.8)' : 'rgba(0,0,0,0.8)' }"
          >创建</p>
          <AnimatePresence>
            <Motion
              v-if="bizHint"
              key="biz-hint"
              as="p"
              :initial="{ opacity: 0, y: -4 }"
              :animate="{ opacity: 1, y: 0 }"
              :exit="{ opacity: 0 }"
              class="text-[10px]"
              style="color: #fb7185;"
            >请先选择所属业务</Motion>
            <p
              v-else
              key="biz-sub"
              class="text-[10px]"
              :style="{ color: isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.25)' }"
            >Genesis Anchor · 生产力起点</p>
          </AnimatePresence>
        </div>
      </div>
    </div>

    <!-- Section label -->
    <div class="flex items-center justify-between px-2 mb-2 mt-2 flex-shrink-0">
      <p
        class="text-[11px] uppercase tracking-[0.2em]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.2)' }"
      >Infinite Stream</p>
      <span
        class="text-[10px]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.2)' }"
      >{{ allSorted.length }} 项</span>
    </div>

    <!-- Scroll area -->
    <div class="flex-1 min-h-0 relative overflow-hidden flex">
      <div
        class="absolute left-[21px] top-0 bottom-0 w-[2px] z-0"
        :style="{
          background: `linear-gradient(180deg, ${rimColor}90, ${rimColor}50, ${rimColor}08)`,
          boxShadow: `0 0 10px ${rimColor}35`,
        }"
      />

      <div
        class="flex-1 overflow-y-auto flex flex-col gap-3 relative z-10 pr-4"
        style="scrollbar-width: none; scroll-behavior: auto; overscroll-behavior: contain;"
      >
        <template v-if="isLoading">
          <GlassSkeleton
            v-for="i in [0, 1, 2, 3]"
            :key="i"
            :is-dark="isDark"
            :rim-color="rimColor"
            :index="i"
          />
        </template>
        <template v-else>
          <Motion
            v-for="(t, i) in allSorted"
            :key="t.id"
            :initial="{ opacity: 0, x: 30 }"
            :animate="{ opacity: 1, x: 0 }"
            :transition="{ delay: 0.04 + i * 0.03, type: 'spring', ...SPRING }"
            class="flex items-start gap-3 pl-0 cursor-pointer group relative"
            @hover-start="emit('focus', t.id)"
            @hover-end="emit('focus', null)"
            @mouseenter="emit('focus', t.id)"
            @mouseleave="emit('focus', null)"
            @click="emit('editTask', t.id)"
            @contextmenu.prevent="(e: MouseEvent) => emit('contextTask', t.id, e.clientX, e.clientY)"
          >
            <!-- Timeline node -->
            <div
              class="flex-shrink-0 w-[44px] flex justify-center relative z-10 pt-[14px]"
            >
              <Motion
                class="w-[16px] h-[16px] rounded-full flex items-center justify-center"
                :while-hover="{ scale: 1.3, boxShadow: `0 0 16px ${stColor(t.status)}40` }"
                :transition="{ type: 'spring', ...SPRING }"
                :style="{
                  background: isDark ? 'rgba(10,10,10,0.8)' : 'rgba(245,245,247,0.8)',
                  border: `2px solid ${stColor(t.status)}`,
                  boxShadow: `0 0 8px ${stColor(t.status)}28`,
                }"
              >
                <Motion
                  v-if="t.status === 'running'"
                  class="w-[6px] h-[6px] rounded-full"
                  :style="{ background: stColor(t.status) }"
                  :animate="{ scale: [1, 1.5, 1], opacity: [1, 0.3, 1] }"
                  :transition="{ duration: 1.5, repeat: Infinity }"
                />
                <div
                  v-else
                  class="w-[5px] h-[5px] rounded-full"
                  :style="{ background: stColor(t.status) }"
                />
              </Motion>
            </div>

            <!-- Card body -->
            <Motion
              :while-hover="{ x: -3, boxShadow: `0 4px 24px ${stColor(t.status)}12, 0 0 0 1px ${stColor(t.status)}15` }"
              :transition="{ type: 'spring', ...SPRING }"
              class="flex-1 rounded-xl p-3 min-w-0 relative overflow-hidden"
              :style="{
                background: isDark ? 'rgba(255,255,255,0.035)' : 'rgba(255,255,255,0.6)',
                border: `1px solid ${isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.04)'}`,
              }"
            >
              <div
                class="absolute top-0 left-2 right-2 h-[1px]"
                :style="{ background: `linear-gradient(90deg, transparent, ${rimColor}25, transparent)` }"
              />

              <div class="flex items-center justify-between mb-1.5">
                <div class="flex items-center gap-2">
                  <span class="text-[11px]" :style="{ color: stColor(t.status) }">{{ t.time }}</span>
                  <span
                    class="text-[10px]"
                    :style="{ color: isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)' }"
                  >{{ t.id }}</span>
                </div>
                <span
                  class="text-[10px] px-2 py-0.5 rounded-md"
                  :style="{ background: `${stColor(t.status)}10`, color: stColor(t.status) }"
                >{{ t.duration }}</span>
              </div>
              <p
                class="text-[13px] truncate mb-2"
                :style="{ color: isDark ? 'rgba(255,255,255,0.8)' : 'rgba(0,0,0,0.8)' }"
              >{{ t.title }}</p>
              <div class="flex items-center gap-2.5">
                <div
                  v-if="personByName(t.owner)"
                  class="w-5 h-5 rounded-md flex items-center justify-center text-[8px] text-white"
                  :style="{
                    background: personByName(t.owner)!.color,
                    boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.15)',
                  }"
                >{{ personByName(t.owner)!.avatar }}</div>
                <span
                  class="text-[11px]"
                  :style="{ color: isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.25)' }"
                >{{ t.owner }}</span>
                <template v-if="bizById(t.biz)">
                  <div
                    class="flex items-center gap-1.5 ml-auto px-2 py-0.5 rounded-md"
                    :style="{
                      background: `${bizById(t.biz)!.color}0c`,
                      border: `1px solid ${bizById(t.biz)!.color}15`,
                    }"
                  >
                    <component :is="bizById(t.biz)!.icon" :size="10" :color="bizById(t.biz)!.color" />
                    <span class="text-[9px]" :style="{ color: bizById(t.biz)!.color }">{{ bizById(t.biz)!.label }}</span>
                  </div>
                </template>
              </div>

              <Motion
                v-if="t.p99 > P99_THRESHOLD"
                class="absolute -top-1 -right-1 px-2 py-1 rounded-lg flex items-center gap-1.5 z-20"
                :animate="{
                  boxShadow: [
                    '0 0 6px rgba(249,115,22,0.3)',
                    '0 0 14px rgba(249,115,22,0.6)',
                    '0 0 6px rgba(249,115,22,0.3)',
                  ],
                }"
                :transition="{ duration: 1.5, repeat: Infinity }"
                :style="{
                  background: isDark ? 'rgba(249,115,22,0.15)' : 'rgba(249,115,22,0.1)',
                  border: '1px solid rgba(249,115,22,0.3)',
                }"
              >
                <AlertTriangle :size="10" color="#f97316" />
                <span class="text-[10px]" style="color: #f97316">
                  P99: <Anim :value="t.p99" :decimals="1" suffix="ms" />
                </span>
              </Motion>
            </Motion>
          </Motion>
          <div class="h-[60px] flex-shrink-0" />
        </template>
      </div>

      <div
        class="absolute top-0 left-0 right-4 h-[40px] pointer-events-none z-20"
        :style="{ background: `linear-gradient(to bottom, ${isDark ? 'rgba(10,10,10,0.7)' : 'rgba(245,245,247,0.7)'}, transparent)` }"
      />
      <div
        class="absolute bottom-0 left-0 right-4 h-[50px] pointer-events-none z-20"
        :style="{ background: `linear-gradient(to top, ${isDark ? 'rgba(10,10,10,0.6)' : 'rgba(245,245,247,0.6)'}, transparent)` }"
      />
    </div>
  </div>
</template>
