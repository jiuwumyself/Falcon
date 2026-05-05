<script setup lang="ts">
import { ref, watch } from 'vue'
import { Motion, AnimatePresence } from 'motion-v'
import { X, Loader, AlertCircle, Copy, Check } from 'lucide-vue-next'
import { VueMonacoEditor } from '@guolao/vue-monaco-editor'
import { tasksApi } from '@/lib/api'
import { ApiError } from '@/lib/api'

const props = defineProps<{
  visible: boolean
  taskId: number
  isDark: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const xml = ref('')
const loading = ref(false)
const error = ref('')
const copied = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  xml.value = ''
  try {
    const r = await tasksApi.previewRunXml(props.taskId)
    xml.value = r.xml
  } catch (e) {
    error.value = e instanceof ApiError ? e.humanMessage : String(e)
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.visible, props.taskId] as const,
  ([v]) => { if (v) load() },
  { immediate: true },
)

async function copyXml() {
  try {
    await navigator.clipboard.writeText(xml.value)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  } catch {
    // clipboard 不可用就静默失败
  }
}
</script>

<template>
  <AnimatePresence>
    <template v-if="visible">
      <!-- Backdrop -->
      <Motion
        key="preview-backdrop"
        :initial="{ opacity: 0 }"
        :animate="{ opacity: 1 }"
        :exit="{ opacity: 0 }"
        :transition="{ duration: 0.2 }"
        class="fixed inset-0 z-40 flex items-center justify-center"
        style="background: rgba(0,0,0,0.45); backdrop-filter: blur(3px)"
        @click="emit('close')"
      >
        <!-- Modal panel — stop propagation so click inside doesn't close -->
        <Motion
          key="preview-panel"
          :initial="{ scale: 0.96, opacity: 0 }"
          :animate="{ scale: 1, opacity: 1 }"
          :exit="{ scale: 0.96, opacity: 0 }"
          :transition="{ duration: 0.22, ease: 'easeOut' }"
          class="rounded-xl flex flex-col z-50"
          :style="{
            width: 'min(1200px, 90vw)',
            height: 'min(820px, 85vh)',
            background: isDark ? '#0f0f17' : '#ffffff',
            border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
            boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
          }"
          @click.stop
        >
          <!-- Header -->
          <div
            class="flex items-center justify-between gap-3 px-5 py-3.5 flex-shrink-0"
            :style="{ borderBottom: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}` }"
          >
            <div class="flex-1 min-w-0">
              <p
                class="text-[10px] uppercase tracking-[0.2em] mb-0.5"
                :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
              >预览跑压测用 XML</p>
              <p
                class="text-[12px]"
                :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.55)' }"
              >内存生成 · 已套 Step 2 配置 · 仅预览不写盘</p>
            </div>
            <div class="flex items-center gap-2 flex-shrink-0">
              <button
                v-if="xml && !loading"
                class="px-2.5 py-1 rounded-md flex items-center gap-1 text-[11px] cursor-pointer"
                :style="{
                  background: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)',
                  border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
                  color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.65)',
                }"
                @click="copyXml"
              >
                <component :is="copied ? Check : Copy" :size="11" />
                {{ copied ? '已复制' : '复制' }}
              </button>
              <button
                class="w-7 h-7 rounded-md flex items-center justify-center cursor-pointer"
                :style="{ background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)' }"
                @click="emit('close')"
              >
                <X :size="13" :color="isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.6)'" />
              </button>
            </div>
          </div>

          <!-- Body -->
          <div class="flex-1 min-h-0 overflow-hidden">
            <div
              v-if="loading"
              class="h-full flex items-center justify-center text-[12px]"
              :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }"
            >
              <Motion
                as="div"
                :animate="{ rotate: 360 }"
                :transition="{ duration: 1, repeat: Infinity, ease: 'linear' }"
                class="flex mr-2"
              >
                <Loader :size="14" />
              </Motion>
              生成中…
            </div>

            <div
              v-else-if="error"
              class="px-5 py-4 text-[12px] text-red-500 flex items-start gap-1.5"
            >
              <AlertCircle :size="12" class="mt-0.5 flex-shrink-0" />
              <span>{{ error }}</span>
            </div>

            <VueMonacoEditor
              v-else
              :value="xml"
              language="xml"
              :theme="isDark ? 'vs-dark' : 'vs'"
              :options="{
                readOnly: true,
                fontSize: 12,
                minimap: { enabled: false },
                wordWrap: 'on',
                scrollBeyondLastLine: false,
                automaticLayout: true,
              }"
              height="100%"
            />
          </div>
        </Motion>
      </Motion>
    </template>
  </AnimatePresence>
</template>
