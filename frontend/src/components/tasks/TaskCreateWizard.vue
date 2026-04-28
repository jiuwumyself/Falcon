<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { AnimatePresence, Motion } from 'motion-v'
import {
  Upload, Sliders, Play, LineChart, FileText, X, Loader, RotateCcw, Check,
} from 'lucide-vue-next'
import { apiForm, ApiError } from '@/lib/api'
import { useTheme } from '@/composables/useTheme'
import type { Task, BizCategory } from '@/types/task'
import ScriptTree from './ScriptTree.vue'
import ConfigStage from './ConfigStage.vue'

const props = defineProps<{
  defaultBiz?: BizCategory
  initialTask?: Task | null    // 编辑模式：从列表点进来时传入
}>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'created', task: Task): void }>()

const { theme } = useTheme()
const isDark = computed(() => theme.value === 'dark')

interface Step {
  id: string
  title: string
  subtitle: string
  icon: any
  color: string
  index: string
}

const STEPS: Step[] = [
  { id: 'upload', title: '上传脚本', subtitle: 'Upload', icon: Upload, color: '#3b82f6', index: '01' },
  { id: 'config', title: '任务配置', subtitle: 'Config', icon: Sliders, color: '#8b5cf6', index: '02' },
  { id: 'execute', title: '执行任务', subtitle: 'Execute', icon: Play, color: '#10b981', index: '03' },
  { id: 'analyze', title: '分析数据', subtitle: 'Analyze', icon: LineChart, color: '#f59e0b', index: '04' },
  { id: 'report', title: '生成报告', subtitle: 'Report', icon: FileText, color: '#ec4899', index: '05' },
]

const currentStep = ref(0)
const file = ref<File | null>(null)
const uploading = ref(false)
const uploadError = ref('')
const uploadedTask = ref<Task | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

// Toast for re-upload feedback (auto-hide after 2.5s).
const toast = ref<{ text: string } | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | null = null
function showToast(text: string) {
  toast.value = { text }
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = null }, 2500)
}

// 编辑入口：传入 initialTask 时把它当成"已上传任务"并跳到最远完成的 Step
function applyInitialTask(t: Task | null | undefined) {
  if (!t) return
  uploadedTask.value = t
  currentStep.value = (t.thread_groups_config?.length ?? 0) > 0 ? 1 : 0
}
applyInitialTask(props.initialTask)
watch(() => props.initialTask, (t) => applyInitialTask(t), { immediate: false })

function triggerPicker() {
  if (uploading.value) return
  fileInput.value?.click()
}

// 重新上传：如已配置 Step 2，先确认；否则直接打开文件选择器
function triggerReupload() {
  if (uploading.value) return
  if ((uploadedTask.value?.thread_groups_config?.length ?? 0) > 0) {
    const ok = confirm('脚本替换后，已配置的运行参数和绑定的 CSV 将被清空。是否继续？')
    if (!ok) return
  }
  fileInput.value?.click()
}

// Drag-over visual state. Use a depth counter so moving over child nodes
// doesn't flicker (each child entry fires dragenter, each exit fires dragleave).
const dragActive = ref(false)
let dragDepth = 0

function onDragEnter(e: DragEvent) {
  if (uploading.value) return
  if (!e.dataTransfer?.types?.includes('Files')) return
  dragDepth++
  dragActive.value = true
}

function onDragLeave() {
  dragDepth = Math.max(0, dragDepth - 1)
  if (dragDepth === 0) dragActive.value = false
}

function resetDragState() {
  dragDepth = 0
  dragActive.value = false
}

const activeStep = computed(() => STEPS[currentStep.value])

function isDone(i: number) {
  return i === 0 && !!uploadedTask.value
}

function canEnterStep(i: number) {
  // Step 0 always reachable. Others require step 0 completed.
  return i === 0 || !!uploadedTask.value
}

function onStepClick(i: number) {
  if (!canEnterStep(i)) return
  currentStep.value = i
}

function onFile(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  if (!f) return
  handleFile(f)
  // allow re-picking the same file after an error
  input.value = ''
}

function onDrop(e: DragEvent) {
  resetDragState()
  const f = e.dataTransfer?.files?.[0]
  if (f) handleFile(f)
}

const MAX_JMX_SIZE = 10 * 1024 * 1024  // keep in sync with Django settings.MAX_UPLOAD_SIZE

function handleFile(f: File) {
  if (!/\.jmx$/i.test(f.name)) {
    uploadError.value = '仅支持 .jmx 文件'
    return
  }
  if (f.size > MAX_JMX_SIZE) {
    uploadError.value = '文件超过 10MB 上限'
    return
  }
  file.value = f
  uploadError.value = ''
  doUpload()
}

async function doUpload() {
  if (!file.value || uploading.value) return
  uploading.value = true
  uploadError.value = ''
  const wasReplacing = !!uploadedTask.value
  const hadConfig = (uploadedTask.value?.thread_groups_config?.length ?? 0) > 0
  try {
    const fd = new FormData()
    fd.append('jmx_file', file.value)

    let task: Task
    if (uploadedTask.value) {
      // 覆盖当前任务的 JMX：保留 title / biz / description / created_at；
      // 后端会清空 thread_groups_config + 解除 CSV 绑定
      task = await apiForm<Task>(`/tasks/${uploadedTask.value.id}/replace-jmx/`, fd)
    } else {
      fd.append('title', file.value.name.replace(/\.jmx$/i, ''))
      fd.append('description', '')
      fd.append('biz_category', props.defaultBiz ?? 'shared')
      task = await apiForm<Task>('/tasks/', fd)
      emit('created', task)
    }
    uploadedTask.value = task
    if (wasReplacing) {
      showToast(hadConfig ? '脚本已替换，请重新配置 Step 2' : '脚本已替换')
    }
  } catch (e) {
    uploadError.value = e instanceof ApiError ? e.humanMessage : String(e)
  } finally {
    uploading.value = false
  }
}

const panelGlass = computed(() => ({
  background: isDark.value ? 'rgba(255,255,255,0.025)' : 'rgba(255,255,255,0.5)',
  backdropFilter: 'blur(40px)',
  border: `1px solid ${isDark.value ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'}`,
  borderRadius: '20px',
  boxShadow: isDark.value
    ? `0 8px 40px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.04)`
    : `0 8px 40px rgba(0,0,0,0.06), inset 0 1px 0 rgba(255,255,255,0.6)`,
}))
</script>

<template>
  <Motion
    :initial="{ opacity: 0, y: 6 }"
    :animate="{ opacity: 1, y: 0 }"
    :transition="{ duration: 0.35 }"
    class="w-full h-full overflow-hidden"
    :style="panelGlass"
  >
    <div class="flex h-full w-full">
      <!-- ═══ Left spine: vertical stepper ═══ -->
      <aside
        class="w-[104px] flex-shrink-0 flex flex-col items-stretch py-5 px-2"
        :style="{
          borderRight: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)'}`,
        }"
      >
        <template v-for="(s, i) in STEPS" :key="s.id">
          <!-- Node row -->
          <button
            class="relative flex flex-col items-center py-2 px-1 rounded-lg transition-colors select-none"
            :class="canEnterStep(i) ? 'cursor-pointer' : 'cursor-not-allowed'"
            :style="{
              opacity: canEnterStep(i) ? 1 : 0.35,
              background: currentStep === i
                ? (isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)')
                : 'transparent',
            }"
            @click="onStepClick(i)"
          >
            <!-- Circle -->
            <div
              class="w-9 h-9 rounded-full flex items-center justify-center transition-all"
              :style="{
                background: isDone(i)
                  ? s.color
                  : currentStep === i
                    ? `${s.color}22`
                    : isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)',
                border: `1.5px solid ${
                  currentStep === i || isDone(i)
                    ? s.color
                    : isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'
                }`,
                boxShadow: currentStep === i ? `0 0 0 4px ${s.color}1a` : 'none',
              }"
            >
              <Check v-if="isDone(i)" :size="14" color="#fff" />
              <Motion
                v-else-if="i === 0 && uploading"
                as="div"
                :animate="{ rotate: 360 }"
                :transition="{ duration: 1, repeat: Infinity, ease: 'linear' }"
                class="flex"
              >
                <Loader :size="14" :color="s.color" />
              </Motion>
              <component
                v-else
                :is="s.icon"
                :size="14"
                :color="currentStep === i ? s.color : isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)'"
              />
            </div>

            <!-- Labels -->
            <p
              class="text-[9px] tracking-[0.2em] mt-1.5"
              :style="{
                color: currentStep === i ? `${s.color}cc` : isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.35)',
              }"
            >{{ s.index }}</p>
            <p
              class="text-[11.5px] leading-tight mt-0.5"
              :style="{
                color: currentStep === i
                  ? (isDark ? '#fff' : '#1a1a2e')
                  : isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)',
                fontWeight: currentStep === i ? 500 : 400,
              }"
            >{{ s.title }}</p>
            <p
              class="text-[8px] tracking-[0.1em] uppercase mt-0.5"
              :style="{
                color: currentStep === i ? `${s.color}99` : isDark ? 'rgba(255,255,255,0.22)' : 'rgba(0,0,0,0.3)',
              }"
            >{{ s.subtitle }}</p>
          </button>

          <!-- Connector line (stretches to fill spine height) -->
          <div
            v-if="i < STEPS.length - 1"
            class="w-[2px] flex-1 min-h-3 mx-auto my-1 rounded-full"
            :style="{
              background: isDone(i)
                ? s.color
                : isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)',
              opacity: isDone(i) ? 1 : 0.55,
            }"
          />
        </template>
      </aside>

      <!-- ═══ Right content ═══ -->
      <main class="flex-1 min-w-0 relative overflow-hidden">
        <!-- Floating close -->
        <button
          class="absolute top-3 right-3 w-7 h-7 rounded-full flex items-center justify-center cursor-pointer z-20"
          :style="{
            background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)',
            border: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)'}`,
          }"
          @click="emit('close')"
        >
          <X :size="13" :color="isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)'" />
        </button>

        <!-- Toast (re-upload feedback) -->
        <AnimatePresence>
          <Motion
            v-if="toast"
            key="toast"
            :initial="{ opacity: 0, y: -8 }"
            :animate="{ opacity: 1, y: 0 }"
            :exit="{ opacity: 0, y: -8 }"
            :transition="{ duration: 0.2 }"
            class="absolute top-3 left-1/2 -translate-x-1/2 z-30 px-3 py-1.5 rounded-lg text-[12px] flex items-center gap-1.5"
            :style="{
              background: isDark ? 'rgba(34,197,94,0.15)' : 'rgba(34,197,94,0.1)',
              border: '1px solid rgba(34,197,94,0.3)',
              color: '#22c55e',
            }"
          >
            <Check :size="13" />
            <span>{{ toast.text }}</span>
          </Motion>
        </AnimatePresence>

        <AnimatePresence mode="wait">
          <Motion
            :key="activeStep.id"
            :initial="{ opacity: 0, x: 10 }"
            :animate="{ opacity: 1, x: 0 }"
            :exit="{ opacity: 0, x: -10 }"
            :transition="{ duration: 0.22 }"
            class="h-full w-full overflow-y-auto pl-8 pr-12 py-6"
          >
            <!-- 01 · Upload: dropzone → 同步显示组件树（不切换步骤） -->
            <template v-if="activeStep.id === 'upload'">
              <!-- Shared hidden input: used by both dropzone click and "重新上传" button -->
              <input
                ref="fileInput"
                type="file"
                accept=".jmx"
                class="hidden"
                @change="onFile"
              />

              <!-- ① 未上传：居中 dropzone -->
              <div v-if="!uploadedTask" class="h-full flex items-center justify-center">
                <div class="w-full max-w-[720px]">
                  <div
                    class="flex flex-col items-center justify-center gap-3 py-16 px-10 rounded-2xl select-none transition-all duration-200"
                    :class="uploading ? 'cursor-wait' : 'cursor-pointer'"
                    :style="{
                      background: dragActive
                        ? (isDark ? 'rgba(59,130,246,0.14)' : 'rgba(59,130,246,0.08)')
                        : (isDark ? 'rgba(59,130,246,0.05)' : 'rgba(59,130,246,0.03)'),
                      border: `1.5px dashed ${
                        dragActive
                          ? '#3b82f6'
                          : file
                            ? 'rgba(59,130,246,0.6)'
                            : 'rgba(59,130,246,0.3)'
                      }`,
                      transform: dragActive ? 'scale(1.01)' : 'scale(1)',
                      boxShadow: dragActive
                        ? '0 0 0 4px rgba(59,130,246,0.12)'
                        : 'none',
                      pointerEvents: uploading ? 'none' : 'auto',
                    }"
                    @click="triggerPicker"
                    @dragenter.prevent="onDragEnter"
                    @dragleave.prevent="onDragLeave"
                    @dragover.prevent
                    @drop.prevent="onDrop"
                  >
                    <div
                      class="w-16 h-16 rounded-2xl flex items-center justify-center"
                      style="background: rgba(59,130,246,0.1)"
                    >
                      <Motion
                        v-if="uploading"
                        as="div"
                        :animate="{ rotate: 360 }"
                        :transition="{ duration: 1, repeat: Infinity, ease: 'linear' }"
                        class="flex"
                      >
                        <Loader :size="28" color="#3b82f6" />
                      </Motion>
                      <Upload v-else :size="28" color="#3b82f6" />
                    </div>

                    <div class="text-center">
                      <p
                        class="text-[16px] tracking-tight"
                        :style="{ color: dragActive ? '#3b82f6' : (isDark ? '#fff' : '#1a1a2e') }"
                      >
                        <template v-if="uploading">保存中… {{ file?.name ?? '' }}</template>
                        <template v-else-if="dragActive">松开即可上传</template>
                        <template v-else>{{ file?.name ?? '拖入 JMeter 脚本开始' }}</template>
                      </p>
                      <p
                        class="text-[11.5px] mt-1.5"
                        :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
                      >
                        仅支持 .jmx 文件
                      </p>
                    </div>
                  </div>

                  <p v-if="uploadError" class="text-[12px] text-red-500 mt-3 text-center">{{ uploadError }}</p>
                </div>
              </div>

              <!-- ② 已上传：header（filename + 重新上传）+ 组件树 -->
              <div v-else class="h-full flex flex-col min-h-0">
                <div class="flex items-start gap-3 mb-4 flex-shrink-0">
                  <div class="flex-1 min-w-0">
                    <p
                      class="text-[15px] tracking-tight truncate"
                      :style="{ color: isDark ? '#fff' : '#1a1a2e' }"
                    >
                      {{ uploadedTask.title }}
                    </p>
                    <p
                      class="text-[11px] mt-0.5 truncate"
                      :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
                    >
                      {{ uploadedTask.jmx_filename }} · 启用 / 禁用组件
                    </p>
                  </div>
                  <button
                    class="px-3 py-1.5 rounded-lg text-[12px] flex items-center gap-1.5 flex-shrink-0 cursor-pointer disabled:opacity-50"
                    :disabled="uploading"
                    :style="{
                      background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)',
                      color: isDark ? 'rgba(255,255,255,0.75)' : 'rgba(0,0,0,0.65)',
                      border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)'}`,
                    }"
                    @click="triggerReupload"
                  >
                    <Motion
                      v-if="uploading"
                      as="div"
                      :animate="{ rotate: 360 }"
                      :transition="{ duration: 1, repeat: Infinity, ease: 'linear' }"
                      class="flex"
                    >
                      <Loader :size="12" />
                    </Motion>
                    <RotateCcw v-else :size="12" />
                    {{ uploading ? '上传中…' : '重新上传' }}
                  </button>
                </div>

                <p
                  v-if="uploadError"
                  class="text-[12px] text-red-500 mb-2 flex-shrink-0"
                >{{ uploadError }}</p>

                <div class="flex-1 min-h-0 overflow-y-auto">
                  <ScriptTree
                    :task="uploadedTask"
                    :is-dark="isDark"
                    @task-updated="uploadedTask = $event"
                  />
                </div>
              </div>
            </template>

            <!-- 02 · Task configuration — 线程组替换 + 模式预设 + 校验 -->
            <template v-else-if="activeStep.id === 'config'">
              <ConfigStage
                v-if="uploadedTask"
                :task="uploadedTask"
                :is-dark="isDark"
                @task-updated="uploadedTask = $event"
              />
            </template>

            <!-- 03-05 · Placeholders -->
            <template v-else>
              <div class="h-full flex flex-col items-center justify-center">
                <div
                  class="w-16 h-16 rounded-2xl flex items-center justify-center mb-4"
                  :style="{ background: `${activeStep.color}10` }"
                >
                  <component :is="activeStep.icon" :size="26" :color="activeStep.color" />
                </div>
                <p
                  class="text-[14px] mb-1"
                  :style="{ color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)' }"
                >v1.1 即将推出</p>
                <p
                  class="text-[12px] text-center max-w-[360px]"
                  :style="{ color: isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.4)' }"
                >
                  <template v-if="activeStep.id === 'execute'">触发 JMeter CLI、查看进度、取消运行</template>
                  <template v-else-if="activeStep.id === 'analyze'">实时 RPS / P99 / 错误率图表与异常定位</template>
                  <template v-else>AI 根据 run 自动生成分析文字、导出 Word 报告</template>
                </p>
              </div>
            </template>
          </Motion>
        </AnimatePresence>
      </main>
    </div>
  </Motion>
</template>
