<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { Motion, AnimatePresence } from 'motion-v'
import { X, Loader, Save, AlertCircle } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import type { JmxComponent, ComponentDetail } from '@/types/task'
import HttpSamplerForm from './detail/HttpSamplerForm.vue'
import HeaderManagerForm from './detail/HeaderManagerForm.vue'

const props = defineProps<{
  node: JmxComponent | null
  taskId: number
  isDark: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved', newTree: JmxComponent[]): void
}>()

const detail = ref<ComponentDetail | null>(null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')

async function load() {
  if (!props.node) return
  loading.value = true
  error.value = ''
  detail.value = null
  try {
    detail.value = await api<ComponentDetail>(
      `/tasks/${props.taskId}/components/detail/?path=${encodeURIComponent(props.node.path)}`,
    )
  } catch (e) {
    error.value = e instanceof ApiError ? e.humanMessage : String(e)
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!props.node || !detail.value) return
  saving.value = true
  error.value = ''
  try {
    const { kind, ...rest } = detail.value
    const newTree = await api<JmxComponent[]>(
      `/tasks/${props.taskId}/components/detail/`,
      {
        method: 'PATCH',
        body: JSON.stringify({ path: props.node.path, kind, fields: rest }),
      },
    )
    emit('saved', newTree)
    emit('close')
  } catch (e) {
    error.value = e instanceof ApiError ? e.humanMessage : String(e)
  } finally {
    saving.value = false
  }
}

watch(() => props.node?.path, (p) => { if (p) load() }, { immediate: true })

const title = computed(() => {
  if (!props.node) return ''
  return `${props.node.testname || '(未命名)'} · ${props.node.tag}`
})
</script>

<template>
  <AnimatePresence>
    <template v-if="node">
      <!-- Backdrop -->
      <Motion
        key="backdrop"
        :initial="{ opacity: 0 }"
        :animate="{ opacity: 1 }"
        :exit="{ opacity: 0 }"
        :transition="{ duration: 0.2 }"
        class="fixed inset-0 z-40"
        style="background: rgba(0,0,0,0.3); backdrop-filter: blur(2px)"
        @click="emit('close')"
      />
      <!-- Drawer -->
      <Motion
        key="drawer"
        :initial="{ x: 420 }"
        :animate="{ x: 0 }"
        :exit="{ x: 420 }"
        :transition="{ duration: 0.28, ease: 'easeOut' }"
        class="fixed top-0 right-0 bottom-0 w-[420px] z-50 flex flex-col"
        :style="{
          background: isDark ? '#0f0f17' : '#ffffff',
          borderLeft: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
          boxShadow: '-8px 0 30px rgba(0,0,0,0.15)',
        }"
      >
        <!-- Header -->
        <div
          class="flex items-start justify-between gap-3 px-5 py-4 flex-shrink-0"
          :style="{ borderBottom: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}` }"
        >
          <div class="flex-1 min-w-0">
            <p
              class="text-[11px] uppercase tracking-wider mb-0.5"
              :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
            >编辑组件</p>
            <p
              class="text-[14px] truncate"
              :style="{ color: isDark ? '#fff' : '#1a1a2e' }"
            >{{ title }}</p>
          </div>
          <button
            class="w-7 h-7 rounded-md flex items-center justify-center cursor-pointer flex-shrink-0"
            :style="{ background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)' }"
            @click="emit('close')"
          >
            <X :size="13" :color="isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.6)'" />
          </button>
        </div>

        <!-- Body -->
        <div class="flex-1 overflow-y-auto px-5 py-5">
          <div
            v-if="loading"
            class="flex items-center gap-2 text-[12px] py-3"
            :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }"
          >
            <Motion
              as="div"
              :animate="{ rotate: 360 }"
              :transition="{ duration: 1, repeat: Infinity, ease: 'linear' }"
              class="flex"
            >
              <Loader :size="14" />
            </Motion>
            加载中…
          </div>

          <p
            v-if="error"
            class="text-[12px] text-red-500 mb-3 flex items-center gap-1"
          >
            <AlertCircle :size="12" /> {{ error }}
          </p>

          <template v-if="detail">
            <HttpSamplerForm
              v-if="detail.kind === 'HTTPSamplerProxy'"
              :detail="detail"
              :is-dark="isDark"
              @update:detail="detail = $event"
            />
            <HeaderManagerForm
              v-else-if="detail.kind === 'HeaderManager'"
              :detail="detail"
              :is-dark="isDark"
              @update:detail="detail = $event"
            />
          </template>
        </div>

        <!-- Footer -->
        <div
          class="flex items-center justify-end gap-2 px-5 py-3 flex-shrink-0"
          :style="{ borderTop: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}` }"
        >
          <button
            class="px-3 py-1.5 rounded-md text-[12px] cursor-pointer"
            :style="{
              background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)',
              color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)',
              border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
            }"
            @click="emit('close')"
          >取消</button>
          <button
            class="px-3 py-1.5 rounded-md text-[12px] text-white flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
            :disabled="!detail || loading || saving"
            style="background: linear-gradient(135deg, #3b82f6, #8b5cf6)"
            @click="save"
          >
            <Save :size="12" />
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </div>
      </Motion>
    </template>
  </AnimatePresence>
</template>
