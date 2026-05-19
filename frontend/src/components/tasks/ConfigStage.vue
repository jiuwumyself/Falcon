<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Motion } from 'motion-v'
import {
  Save, PlayCircle, Loader, AlertCircle, CheckCircle2, Info, FileCode2,
} from 'lucide-vue-next'
import { api, ApiError, tasksApi } from '@/lib/api'
import type {
  Task, ThreadGroupInfo, ThreadGroupConfig, ThreadGroupsResponse,
  ValidateResult, ValidateResponse, ExecutedTg, ScenarioId, TGKind,
} from '@/types/task'
import ScenarioTabs from './config/ScenarioTabs.vue'
import ThreadGroupPicker from './config/ThreadGroupPicker.vue'
import TgParamsForm from './config/TgParamsForm.vue'
import ThreadGroupChart from './config/ThreadGroupChart.vue'
import EnvironmentPicker from './config/EnvironmentPicker.vue'
import ServicePicker from './config/ServicePicker.vue'
import ValidateResultTable from './config/ValidateResultTable.vue'
import PreviewRunXmlModal from './config/PreviewRunXmlModal.vue'
import { scenarioById, inferScenarioFromKind, SCENARIOS } from './configStageCtx'

const props = defineProps<{
  task: Task
  isDark: boolean
}>()

const emit = defineEmits<{
  (e: 'task-updated', task: Task): void
}>()

const loading = ref(false)
const saving = ref(false)
const validating = ref(false)
const loadError = ref('')
const saveError = ref('')
const validateError = ref('')
const savedAt = ref<number>(0)

const threadGroups = ref<ThreadGroupInfo[]>([])    // 仅启用的 TG
const disabledNames = ref<string[]>([])            // 禁用的 TG 名字（仅展示提示）
const configs = ref<ThreadGroupConfig[]>([])       // 各 TG 的当前配置（同 path 对齐）
const currentPath = ref<string>('')                // 当前在编辑哪个 TG

// 每个 TG 每个场景的"上次编辑值"快照，切走前存、切回时恢复，
// 避免「场景切换 → 切回 → 参数被默认值覆盖」。session 级，不入库。
const scenarioMemo = ref<Record<string, Partial<Record<ScenarioId, { kind: TGKind; params: Record<string, any> }>>>>({})

function cloneParams(params: Record<string, any>): Record<string, any> {
  return JSON.parse(JSON.stringify(params))
}

function memoSet(path: string, scenario: ScenarioId, kind: TGKind, params: Record<string, any>) {
  if (!scenarioMemo.value[path]) scenarioMemo.value[path] = {}
  scenarioMemo.value[path][scenario] = { kind, params: cloneParams(params) }
}

function memoGet(path: string, scenario: ScenarioId) {
  return scenarioMemo.value[path]?.[scenario]
}
const environmentId = ref<number | null>(null)
const serviceNames = ref<string[]>([])
const serviceSaving = ref(false)
const serviceError = ref('')
const validateResults = ref<ValidateResult[]>([])
const validateWarnings = ref<string[]>([])
const validateExecutedTgs = ref<ExecutedTg[]>([])
const validateTriggered = ref(false)
const showPreviewXml = ref(false)

// 当前 TG 的配置 (双向绑定代理)
const currentConfig = computed<ThreadGroupConfig | null>(() => {
  return configs.value.find((c) => c.path === currentPath.value) ?? null
})

const currentScenario = computed<ScenarioId>(() => {
  return currentConfig.value?.scenario ?? 'load'
})

const currentScenarioDef = computed(() => scenarioById(currentScenario.value))

// 给 ThreadGroupPicker 展示每个 TG 已选的场景
const scenarioByPath = computed<Record<string, ScenarioId>>(() => {
  const out: Record<string, ScenarioId> = {}
  for (const c of configs.value) {
    out[c.path] = c.scenario ?? inferScenarioFromKind(c.kind)
  }
  return out
})

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const r = await api<ThreadGroupsResponse>(`/tasks/${props.task.id}/thread-groups/`)
    const enabled = r.thread_groups.filter((tg) => tg.enabled)
    threadGroups.value = enabled
    disabledNames.value = r.thread_groups
      .filter((tg) => !tg.enabled)
      .map((tg) => tg.testname || `TG ${tg.path}`)

    const savedByPath = new Map<string, ThreadGroupConfig>()
    for (const c of r.saved_config) savedByPath.set(c.path, c)

    scenarioMemo.value = {}
    configs.value = enabled.map((tg) => {
      const saved = savedByPath.get(tg.path)
      if (saved) {
        // 兼容老数据：没 scenario 字段就按 kind 反推
        const scenario = saved.scenario ?? inferScenarioFromKind(saved.kind)
        const cfg: ThreadGroupConfig = { ...saved, scenario, params: cloneParams(saved.params) }
        memoSet(tg.path, scenario, cfg.kind, cfg.params)
        return cfg
      }
      // 新 TG：默认 load 场景
      const def = SCENARIOS.find((s) => s.id === 'load')!
      const cfg: ThreadGroupConfig = {
        path: tg.path,
        scenario: 'load',
        kind: def.kind,
        params: cloneParams(def.defaultParams),
      }
      memoSet(tg.path, 'load', cfg.kind, cfg.params)
      return cfg
    })

    currentPath.value = enabled[0]?.path ?? ''
    environmentId.value = r.environment ?? null
    serviceNames.value = Array.isArray(props.task.service_names) ? [...props.task.service_names] : []
  } catch (e) {
    loadError.value = e instanceof ApiError ? e.humanMessage : String(e)
  } finally {
    loading.value = false
  }
}

watch(() => props.task.id, load, { immediate: true })

// —— 场景切换：先快照当前 scenario 的参数，再从 memo 恢复 next 的参数（无则取默认）—— //
function onScenarioChange(next: ScenarioId) {
  const i = configs.value.findIndex((c) => c.path === currentPath.value)
  if (i < 0) return
  const cur = configs.value[i]
  if (cur.scenario === next) return

  // 1. 把当前 scenario 的最新编辑值存进 memo
  if (cur.scenario) {
    memoSet(cur.path, cur.scenario, cur.kind, cur.params)
  }

  // 2. 从 memo 恢复 next；没有则用场景默认
  const cached = memoGet(cur.path, next)
  const def = scenarioById(next)
  const arr = configs.value.slice()
  arr[i] = {
    path: cur.path,
    scenario: next,
    kind: cached?.kind ?? def.kind,
    params: cached ? cloneParams(cached.params) : cloneParams(def.defaultParams),
  }
  configs.value = arr
}

// —— 参数微调：保留当前 TG 的 scenario / kind，并同步进 memo —— //
function onParamsChange(next: ThreadGroupConfig) {
  const i = configs.value.findIndex((c) => c.path === currentPath.value)
  if (i < 0) return
  const arr = configs.value.slice()
  arr[i] = next
  configs.value = arr
  if (next.scenario) {
    memoSet(next.path, next.scenario, next.kind, next.params)
  }
}

// service_names 改变时单独 PATCH /tasks/:id/，与线程组配置解耦
async function onServiceNamesChange(next: string[]) {
  serviceNames.value = next
  serviceError.value = ''
  serviceSaving.value = true
  try {
    const updated = await tasksApi.update(props.task.id, { service_names: next })
    emit('task-updated', updated)
  } catch (e) {
    serviceError.value = e instanceof ApiError ? e.humanMessage : String(e)
  } finally {
    serviceSaving.value = false
  }
}

async function save() {
  if (saving.value) return
  saving.value = true
  saveError.value = ''
  try {
    const updated = await api<Task>(`/tasks/${props.task.id}/thread-groups/`, {
      method: 'PATCH',
      body: JSON.stringify({
        thread_groups: configs.value,
        environment_id: environmentId.value,
      }),
    })
    emit('task-updated', updated)
    savedAt.value = Date.now()
  } catch (e) {
    saveError.value = e instanceof ApiError ? e.humanMessage : String(e)
  } finally {
    saving.value = false
  }
}

async function validate() {
  if (validating.value) return
  validating.value = true
  validateError.value = ''
  validateTriggered.value = true
  try {
    const r = await api<ValidateResponse>(
      `/tasks/${props.task.id}/validate/`,
      {
        method: 'POST',
        body: JSON.stringify({ environment_id: environmentId.value }),
      },
    )
    validateResults.value = r.results
    validateWarnings.value = r.warnings || []
    validateExecutedTgs.value = r.executed_tgs || []
  } catch (e) {
    validateError.value = e instanceof ApiError ? e.humanMessage : String(e)
  } finally {
    validating.value = false
  }
}

const showSaved = computed(() => savedAt.value > 0 && Date.now() - savedAt.value < 4000)
</script>

<template>
  <div class="h-full flex flex-col gap-3 min-h-0">
    <!-- Loading / empty -->
    <div
      v-if="loading"
      class="flex items-center gap-2 text-[12px] py-4"
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
      加载配置…
    </div>

    <p v-if="loadError" class="text-[12px] text-red-500 flex items-center gap-1">
      <AlertCircle :size="12" /> {{ loadError }}
    </p>

    <template v-if="!loading && !loadError">
      <!-- ① TG Picker (多 TG 才显示) -->
      <ThreadGroupPicker
        :thread-groups="threadGroups"
        :scenario-by-path="scenarioByPath"
        :current-path="currentPath"
        :is-dark="isDark"
        @update:current-path="currentPath = $event"
      />

      <!-- 禁用 TG 的提示 (如果有) -->
      <div
        v-if="disabledNames.length"
        class="flex items-start gap-2 px-3 py-1.5 rounded-md text-[11px] flex-shrink-0"
        :style="{
          background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.025)',
          color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)',
        }"
      >
        <Info :size="11" class="flex-shrink-0 mt-0.5" />
        <span>
          Step 1 禁用了 {{ disabledNames.length }} 个线程组（{{ disabledNames.join('、') }}），
          保存时保留原样不参与配置；执行压测时 JMeter 会跳过。
        </span>
      </div>

      <!-- ② Scenario Tabs + description -->
      <div v-if="currentConfig" class="flex-shrink-0">
        <ScenarioTabs
          :model-value="currentScenario"
          :is-dark="isDark"
          @update:model-value="onScenarioChange"
        />
      </div>

      <!-- ③ Left form / Right chart -->
      <div
        v-if="currentConfig"
        class="flex-1 min-h-0 grid gap-4"
        :style="{ gridTemplateColumns: '35fr 65fr' }"
      >
        <!-- Left column: params + env + actions -->
        <div class="flex flex-col gap-4 min-h-0 overflow-y-auto pr-1">
          <TgParamsForm
            :config="currentConfig"
            :is-dark="isDark"
            @update:config="onParamsChange"
          />

          <div class="flex flex-col gap-2">
            <p
              class="text-[10px] uppercase tracking-[0.2em]"
              :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }"
            >执行环境</p>
            <EnvironmentPicker v-model="environmentId" :is-dark="isDark" />
          </div>

          <div class="flex flex-col gap-2">
            <p
              class="text-[10px] uppercase tracking-[0.2em] flex items-center gap-1.5"
              :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }"
            >
              被压测服务
              <Loader v-if="serviceSaving" :size="10" class="animate-spin" />
            </p>
            <ServicePicker
              :model-value="serviceNames"
              :is-dark="isDark"
              @update:model-value="onServiceNamesChange"
            />
            <p v-if="serviceError" class="text-[11px] text-red-500 flex items-center gap-1">
              <AlertCircle :size="11" /> {{ serviceError }}
            </p>
          </div>

          <div class="flex flex-col gap-2 mt-auto pt-3">
            <div v-if="saveError" class="text-[11px] text-red-500 flex items-center gap-1">
              <AlertCircle :size="11" /> {{ saveError }}
            </div>
            <div v-if="showSaved" class="text-[11px] flex items-center gap-1" style="color: #10b981">
              <CheckCircle2 :size="11" /> 已保存 · 跑压测时按当前配置生成
            </div>
            <button
              class="self-start flex items-center gap-1 text-[11px] cursor-pointer hover:underline"
              :style="{ color: isDark ? 'rgba(167,139,250,0.85)' : '#7c3aed' }"
              @click="showPreviewXml = true"
            >
              <FileCode2 :size="11" />
              预览跑压测用 XML
            </button>
            <div class="flex gap-2">
              <button
                class="flex-1 px-3 py-2 rounded-lg text-[12px] flex items-center justify-center gap-1.5 cursor-pointer disabled:opacity-50"
                :disabled="validating || !configs.length"
                :style="{
                  background: isDark ? 'rgba(59,130,246,0.12)' : 'rgba(59,130,246,0.08)',
                  color: '#3b82f6',
                  border: `1px solid ${isDark ? 'rgba(59,130,246,0.25)' : 'rgba(59,130,246,0.22)'}`,
                }"
                @click="validate"
              >
                <Motion
                  v-if="validating"
                  as="div"
                  :animate="{ rotate: 360 }"
                  :transition="{ duration: 1, repeat: Infinity, ease: 'linear' }"
                  class="flex"
                >
                  <Loader :size="12" />
                </Motion>
                <PlayCircle v-else :size="12" />
                {{ validating ? '试跑中…' : '试跑' }}
              </button>
              <button
                class="flex-1 px-3 py-2 rounded-lg text-[12px] text-white flex items-center justify-center gap-1.5 cursor-pointer disabled:opacity-50"
                :disabled="saving || !configs.length"
                :style="{
                  background: `linear-gradient(135deg, ${currentScenarioDef.color}, ${currentScenarioDef.color}aa)`,
                  boxShadow: `0 4px 14px ${currentScenarioDef.color}44`,
                }"
                @click="save"
              >
                <Motion
                  v-if="saving"
                  as="div"
                  :animate="{ rotate: 360 }"
                  :transition="{ duration: 1, repeat: Infinity, ease: 'linear' }"
                  class="flex"
                >
                  <Loader :size="12" />
                </Motion>
                <Save v-else :size="12" />
                {{ saving ? '保存中…' : '保存配置' }}
              </button>
            </div>
          </div>
        </div>

        <!-- Right column: chart + results -->
        <div class="flex flex-col gap-3 min-h-0">
          <ThreadGroupChart
            :kind="currentConfig.kind"
            :params="currentConfig.params"
            :scenario-color="currentScenarioDef.color"
            :is-dark="isDark"
          />

          <!-- Validate results -->
          <div v-if="validateError" class="text-[11px] text-red-500 flex items-center gap-1">
            <AlertCircle :size="11" /> {{ validateError }}
          </div>
          <div v-if="validateTriggered && !validateError" class="flex-1 min-h-0 overflow-y-auto">
            <ValidateResultTable
              :results="validateResults"
              :warnings="validateWarnings"
              :executed-tgs="validateExecutedTgs"
              :is-dark="isDark"
            />
          </div>
        </div>
      </div>

      <p
        v-else-if="!loading"
        class="text-[12px] py-4 text-center"
        :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
      >该 JMX 里没有启用的线程组</p>
    </template>

    <PreviewRunXmlModal
      :visible="showPreviewXml"
      :task-id="props.task.id"
      :is-dark="isDark"
      @close="showPreviewXml = false"
    />
  </div>
</template>
