<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { History, ChevronDown, Check, Star, Trash2, Loader } from 'lucide-vue-next'
import type { TaskRun, ThreadGroupConfig } from '@/types/task'
import { plannedThreads, formatDuration } from '@/lib/planSummary'
import { runsApi, ApiError } from '@/lib/api'
import { scenarioById, inferScenarioFromKind } from '@/components/tasks/configStageCtx'
import { STATUS_META } from './runStatusMeta'

// 历史 run 下拉。原在 RunControlBar，迁到 RunDashboard 标签行「查看报告」之后。
// 面板 Teleport 到 body + fixed 定位，避开标签行 overflow-x-auto 的裁剪。
const props = defineProps<{
  runs: TaskRun[]
  selectedRun: TaskRun | null
  isDark: boolean
}>()
const emit = defineEmits<{
  (e: 'select', runId: string): void
  (e: 'run-deleted', runId: string): void
}>()

const hoveredRunId = ref<string | null>(null)
const deletingRunId = ref<string | null>(null)
const togglingRunId = ref<string | null>(null)

// 列：状态/时间/时长/VU/成功/场景/基准/记录/删除。全固定 px（表头与数据行两个独立
// grid 用 px 才对齐）；不留大弹性间隙，面板按内容宽度收缩，列距均匀。
const HISTORY_GRID = '54px 84px 74px 40px 48px 72px 40px 44px 28px'

// ─── 下拉开合（面板 fixed 定位，按钮 rect 算位置）────────────────────
const btnRef = ref<HTMLElement | null>(null)
const historyOpen = ref(false)
const panelStyle = ref<Record<string, string>>({})
function openPanel() {
  const el = btnRef.value
  if (el) {
    const r = el.getBoundingClientRect()
    // 面板水平居中对齐「历史」按钮中心，出现在它正下方；贴边时夹取避免溢出
    const half = 280
    const center = Math.min(Math.max(r.left + r.width / 2, half + 8), window.innerWidth - half - 8)
    panelStyle.value = {
      top: `${r.bottom + 6}px`,
      left: `${center}px`,
      transform: 'translateX(-50%)',
    }
  }
  historyOpen.value = true
}
function closeHistory() { historyOpen.value = false }
function toggleHistory() { historyOpen.value ? closeHistory() : openPanel() }
function clickOutsideHandler(e: MouseEvent) {
  const t = e.target as HTMLElement
  if (!t.closest('[data-history-dropdown]')) closeHistory()
}
onMounted(() => document.addEventListener('click', clickOutsideHandler))
onBeforeUnmount(() => document.removeEventListener('click', clickOutsideHandler))

function selectRun(rid: string) { emit('select', rid); closeHistory() }

function fmtRunTitle(r: TaskRun): string {
  if (r.started_at) {
    const d = new Date(r.started_at)
    return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
  }
  return r.run_id.slice(0, 6)
}

// 执行时长（finished - started），取整去掉小数；未结束显 —
function durationLabel(r: TaskRun): string {
  if (!r.started_at || !r.finished_at) return '—'
  const d = (new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 1000
  return d > 0 ? formatDuration(Math.round(d)) : '—'
}

function scenarioOf(cfg: ThreadGroupConfig) {
  return scenarioById(cfg.scenario || inferScenarioFromKind(cfg.kind))
}
// 场景列：单 TG 显场景名(带场景色 pill)，多 TG 显「N 个」(中性色，hover 看明细)
function scenarioColInfo(r: TaskRun): { label: string; color: string | null } {
  const snap = r.thread_groups_config_snapshot || []
  if (snap.length === 0) return { label: '—', color: null }
  if (snap.length === 1) {
    const s = scenarioOf(snap[0])
    return { label: s.label, color: s.color }
  }
  return { label: `${snap.length} 个`, color: null }
}
function scenarioPillStyle(r: TaskRun): Record<string, string> {
  const c = scenarioColInfo(r).color
  return c
    ? { background: `${c}1f`, color: c }
    : { color: props.isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }
}
function plannedVuOf(r: TaskRun): number {
  // snapshot 算 sum(per-TG planned)；snapshot 空（旧 run）退回 r.virtual_users。
  const snap = r.thread_groups_config_snapshot
  if (snap && snap.length > 0) return plannedThreads(snap)
  return r.virtual_users || 0
}
function successRate(r: TaskRun): number {
  return Math.max(0, 100 - (r.error_rate || 0))
}
function successColor(r: TaskRun): string {
  if (r.status === 'pre_checking' || r.status === 'pending') return '#9ca3af'
  const s = successRate(r)
  if (s >= 99) return '#10b981'
  if (s >= 95) return '#f59e0b'
  return '#ef4444'
}

// 「记录」勾选 → 后端 keep（keep=true 的 run 目录永不被自动清理）
async function onToggleKeep(r: TaskRun) {
  if (togglingRunId.value) return
  togglingRunId.value = r.run_id
  try {
    const updated = await runsApi.setKeep(r.run_id, !r.keep)
    r.keep = updated.keep
  } catch (e) {
    window.alert(`保存失败：${e instanceof ApiError ? e.humanMessage : String(e)}`)
  } finally { togglingRunId.value = null }
}

// 历史基准星标 = 每 task 单选；已有别的基准时本行禁用（须先取消当前）
const taskBaselineRunId = computed(() => props.runs.find((r) => r.is_baseline)?.run_id ?? null)
function starDisabled(r: TaskRun): boolean {
  return !!taskBaselineRunId.value && taskBaselineRunId.value !== r.run_id
}
async function onToggleBaseline(r: TaskRun) {
  if (togglingRunId.value || starDisabled(r)) return
  const next = !r.is_baseline
  togglingRunId.value = r.run_id
  try {
    await runsApi.setBaseline(r.run_id, next)
    for (const x of props.runs) x.is_baseline = x.run_id === r.run_id ? next : false
  } catch (e) {
    window.alert(`保存失败：${e instanceof ApiError ? e.humanMessage : String(e)}`)
  } finally { togglingRunId.value = null }
}

async function onDeleteRun(r: TaskRun) {
  if (deletingRunId.value) return
  if (!window.confirm(`确认删除 ${fmtRunTitle(r)} 这次 run？\n该操作会清除磁盘归档 + InfluxDB 数据，不可恢复。\n（表行保留供大盘统计任务历史 run 数。）`)) return
  deletingRunId.value = r.run_id
  try {
    await runsApi.delete(r.run_id)
    emit('run-deleted', r.run_id)
  } catch (e) {
    const msg = e instanceof ApiError ? e.humanMessage : (e instanceof Error ? e.message : String(e))
    window.alert(`删除失败：${msg}`)
  } finally { deletingRunId.value = null }
}
</script>

<template>
  <div v-if="runs.length" ref="btnRef" data-history-dropdown>
    <button
      class="flex items-center gap-1.5 px-3 py-2 text-[12px] cursor-pointer flex-shrink-0 transition-colors"
      :style="{ color: historyOpen
        ? (isDark ? '#fff' : '#1a1a2e')
        : (isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.6)') }"
      :title="`历史 ${runs.length} 次运行`"
      @click.stop="toggleHistory"
    >
      <History :size="12" />
      历史 ({{ runs.length }})
      <ChevronDown :size="10" :style="{ transform: historyOpen ? 'rotate(180deg)' : 'none', transition: 'transform .15s' }" />
    </button>

    <!-- 面板：玻璃拟态 + Teleport 到 body，fixed 定位逃出标签行 overflow 裁剪 -->
    <Teleport to="body">
      <div
        v-if="historyOpen"
        data-history-dropdown
        class="fixed max-h-[380px] overflow-y-auto rounded-xl backdrop-blur-xl"
        :style="{
          top: panelStyle.top,
          left: panelStyle.left,
          transform: panelStyle.transform,
          zIndex: 1000,
          background: isDark ? 'rgba(20,20,26,0.92)' : 'rgba(255,255,255,0.96)',
          border: `1px solid ${isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.07)'}`,
          boxShadow: '0 12px 32px rgba(0,0,0,0.22)',
        }"
      >
        <!-- 表头块（标题 + 列名）：sticky 顶部 -->
        <div
          class="sticky top-0 z-10"
          :style="{
            background: isDark ? 'rgba(20,20,26,0.96)' : 'rgba(255,255,255,0.98)',
            borderBottom: `1px solid ${isDark ? 'rgba(255,255,255,0.07)' : 'rgba(0,0,0,0.06)'}`,
          }"
        >
          <div
            class="px-3 pt-2 pb-1 text-[11px] font-medium flex items-center gap-1.5"
            :style="{ color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.65)' }"
          >
            <History :size="12" /> 运行历史
            <span class="opacity-50">· {{ runs.length }} 次</span>
          </div>
          <div
            class="grid items-center gap-2 px-3 pb-1.5 text-[9.5px] uppercase tracking-wider"
            :style="{ gridTemplateColumns: HISTORY_GRID, color: isDark ? 'rgba(255,255,255,0.38)' : 'rgba(0,0,0,0.38)' }"
          >
            <span>状态</span>
            <span>时间</span>
            <span>时长</span>
            <span>VU</span>
            <span>成功</span>
            <span>场景</span>
            <span class="text-center">基准</span>
            <span class="text-center">记录</span>
            <span></span>
          </div>
        </div>

        <!-- 行 -->
        <div class="py-1">
          <div
            v-for="r in runs"
            :key="r.run_id"
            class="grid items-center gap-2 px-3 py-2 text-[11.5px] transition-colors hover:bg-black/[0.035] dark:hover:bg-white/[0.05]"
            :style="{
              gridTemplateColumns: HISTORY_GRID,
              background: r.run_id === selectedRun?.run_id
                ? (isDark ? 'rgba(59,130,246,0.14)' : 'rgba(59,130,246,0.08)')
                : 'transparent',
              boxShadow: r.run_id === selectedRun?.run_id ? 'inset 2px 0 0 #3b82f6' : 'none',
            }"
          >
            <!-- 状态 -->
            <span
              class="px-1.5 py-0.5 rounded-full text-[10px] whitespace-nowrap truncate justify-self-start"
              :style="{
                background: `${STATUS_META[r.status]?.color || '#6b7280'}1f`,
                color: STATUS_META[r.status]?.color || '#6b7280',
              }"
            >{{ STATUS_META[r.status]?.label || r.status }}</span>

            <!-- 时间（点击切 selectedRun）-->
            <span
              class="tabular-nums cursor-pointer truncate"
              :class="r.run_id === selectedRun?.run_id ? 'font-medium' : ''"
              :style="{
                color: r.run_id === selectedRun?.run_id
                  ? (isDark ? '#93c5fd' : '#2563eb')
                  : (isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.8)'),
              }"
              @click="selectRun(r.run_id)"
            >{{ fmtRunTitle(r) }}</span>

            <!-- 时长 -->
            <span class="text-[10.5px] tabular-nums truncate"
                  :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }"
                  title="执行时长（结束 - 开始）">{{ durationLabel(r) }}</span>

            <!-- VU -->
            <span class="text-[10.5px] tabular-nums"
                  :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }"
                  title="启动时快照的总计划线程数（按各 TG 配置求和）">{{ plannedVuOf(r) }}</span>

            <!-- 成功率 -->
            <span class="text-[10.5px] tabular-nums" :style="{ color: successColor(r) }"
                  title="成功率 = 100 - error_rate">{{ successRate(r).toFixed(0) }}%</span>

            <!-- 场景 pill（+ 多 TG hover 明细）-->
            <span
              class="relative justify-self-start"
              @mouseenter="hoveredRunId = r.run_id"
              @mouseleave="hoveredRunId = null"
            >
              <span
                class="px-1.5 py-0.5 rounded-full text-[10px] whitespace-nowrap"
                :class="(r.thread_groups_config_snapshot?.length || 0) > 1 ? 'cursor-help' : 'cursor-default'"
                :style="scenarioPillStyle(r)"
              >{{ scenarioColInfo(r).label }}</span>
              <div
                v-if="hoveredRunId === r.run_id && (r.thread_groups_config_snapshot?.length || 0) > 1"
                class="absolute left-0 top-full mt-1 px-2 py-1.5 rounded-lg shadow-lg z-30 min-w-[200px] text-[11px]"
                :style="{
                  background: isDark ? 'rgba(20,20,30,0.97)' : 'rgba(255,255,255,0.98)',
                  border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
                  backdropFilter: 'blur(20px)',
                }"
              >
                <div class="text-[10px] uppercase tracking-wider mb-1.5"
                     :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">该 run 跑时 TG 快照</div>
                <div v-for="(cfg, i) in r.thread_groups_config_snapshot" :key="i"
                     class="flex items-center gap-1.5 py-0.5">
                  <span class="w-1.5 h-1.5 rounded-full flex-shrink-0" :style="{ background: scenarioOf(cfg).color }" />
                  <span :style="{ color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.75)' }">{{ scenarioOf(cfg).label }}</span>
                  <span class="ml-auto font-mono text-[10px] opacity-50">{{ cfg.path }}</span>
                </div>
              </div>
            </span>

            <!-- 基准星标（每 task 单选）-->
            <button
              type="button"
              class="flex items-center justify-center rounded cursor-pointer disabled:cursor-not-allowed mx-auto"
              :style="{ opacity: starDisabled(r) ? 0.3 : 1 }"
              :disabled="starDisabled(r) || togglingRunId === r.run_id"
              :title="r.is_baseline ? '取消历史基准'
                : (starDisabled(r) ? '该任务已有基准，先取消当前再设' : '设为历史基准（版本对比基线）')"
              @click.stop="onToggleBaseline(r)"
            >
              <Star :size="13"
                    :color="r.is_baseline ? '#f59e0b' : (isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.28)')"
                    :fill="r.is_baseline ? '#f59e0b' : 'none'" />
            </button>

            <!-- 记录勾选 → 后端 keep -->
            <span
              class="w-3.5 h-3.5 rounded border flex items-center justify-center cursor-pointer mx-auto"
              :style="{
                background: r.keep ? '#3b82f6' : 'transparent',
                borderColor: r.keep ? '#3b82f6' : (isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.3)'),
                opacity: togglingRunId === r.run_id ? 0.5 : 1,
              }"
              :title="r.keep ? '已记录（不会被自动清理）' : '记录此 run 数据（否则约 30 天后自动清理目录）'"
              @click.stop="onToggleKeep(r)"
            >
              <Check v-if="r.keep" :size="9" color="#fff" />
            </span>

            <!-- 删除 -->
            <button
              type="button"
              class="flex items-center justify-center rounded cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed mx-auto"
              :disabled="deletingRunId === r.run_id"
              title="删除该 run（清磁盘 + InfluxDB；表行保留供大盘统计）"
              @click.stop="onDeleteRun(r)"
            >
              <Loader v-if="deletingRunId === r.run_id" :size="12" class="animate-spin" color="#ef4444" />
              <Trash2 v-else :size="12" :color="isDark ? 'rgba(239,68,68,0.85)' : '#ef4444'" />
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
