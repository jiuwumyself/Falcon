<script setup lang="ts">
import { ref, computed, inject, watch, nextTick } from 'vue'
import { Motion } from 'motion-v'
import {
  ChevronRight, Search, ChevronsDownUp, ChevronsUpDown, Paperclip, Package,
} from 'lucide-vue-next'
import type { JmxComponent } from '@/types/task'
import { SCRIPT_TREE_CTX } from './scriptTreeCtx'

const props = defineProps<{
  node: JmxComponent
  depth: number
  isDark: boolean
  busyPaths: Set<string>
  // Whether the chain of parents is all enabled. Used only for visual dimming —
  // children keep their own `enabled` state, JMeter just skips them at runtime
  // when a parent is disabled.
  parentEnabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'toggle', path: string, next: boolean): void
  (e: 'rename', path: string, testname: string): void
  (e: 'edit', node: JmxComponent): void
}>()

// Default: expand first three levels (depth 0/1/2). Deeper stays collapsed,
// user can click chevron to drill further.
const expanded = ref(props.depth < 2)

const ctx = inject(SCRIPT_TREE_CTX, null)

// Root TestPlan hosts the toolbar (search + expand/collapse) instead of an enabled toggle.
const isRootTestPlan = computed(
  () => props.depth === 0 && props.node.tag === 'TestPlan',
)

const isCsvDataSet = computed(() => props.node.tag === 'CSVDataSet')
const isBeanShellPre = computed(() => props.node.tag === 'BeanShellPreProcessor')

const EDITABLE_KINDS = new Set([
  'HTTPSamplerProxy', 'HeaderManager', 'HttpDefaults',
  'JSONPathAssertion', 'BeanShellPostProcessor', 'BeanShellPreProcessor',
  'RegexExtractor', 'JSONPathExtractor', 'CSVDataSet',
])
const isEditable = computed(() => EDITABLE_KINDS.has(props.node.kind || props.node.tag))

// testname 行内编辑：双击 → input，Enter/失焦保存，Esc 取消。
const isEditingName = ref(false)
const editNameValue = ref('')
const nameInput = ref<HTMLInputElement | null>(null)

function startRename() {
  // Root TestPlan 不让改（避免语义和占位 toolbar 冲突）
  if (isRootTestPlan.value) return
  isEditingName.value = true
  editNameValue.value = props.node.testname
  nextTick(() => {
    nameInput.value?.focus()
    nameInput.value?.select()
  })
}

function commitRename() {
  if (!isEditingName.value) return
  const next = editNameValue.value
  isEditingName.value = false
  // 名字没变就别往后端跑一趟
  if (next === props.node.testname) return
  emit('rename', props.node.path, next)
}

function cancelRename() {
  isEditingName.value = false
}

// CSV inline upload state — hidden <input> + click handler; shown only on
// CSVDataSet rows.
const csvInput = ref<HTMLInputElement | null>(null)
const csvUploading = ref(false)

async function onCsvPick(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  input.value = ''  // let user re-pick the same filename later
  if (!f || !ctx) return
  csvUploading.value = true
  try {
    await ctx.uploadCsv(props.node.path, f)
  } catch {
    // Error bubbles up via the tree — ScriptTree already shows the error banner.
    // Flash our own row red too so the failure is visible near the action.
    if (ctx) {
      ctx.errorFlashPath.value = props.node.path
      setTimeout(() => {
        if (ctx.errorFlashPath.value === props.node.path) ctx.errorFlashPath.value = null
      }, 800)
    }
  } finally {
    csvUploading.value = false
  }
}

// Lookup current binding for THIS CSVDataSet from task.csv_bindings.
const csvBinding = computed(() =>
  ctx?.task.value.csv_bindings?.find((b) => b.component_path === props.node.path) ?? null,
)

// JAR inline upload state — hidden <input> + click handler; shown only on
// BeanShellPreProcessor rows.
const jarInput = ref<HTMLInputElement | null>(null)
const jarUploading = ref(false)

async function onJarPick(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  input.value = ''
  if (!f || !ctx) return
  jarUploading.value = true
  try {
    await ctx.uploadJar(props.node.path, f)
  } catch {
    if (ctx) {
      ctx.errorFlashPath.value = props.node.path
      setTimeout(() => {
        if (ctx.errorFlashPath.value === props.node.path) ctx.errorFlashPath.value = null
      }, 800)
    }
  } finally {
    jarUploading.value = false
  }
}

// Auto-expand this row if it (or an ancestor) is marked "must be visible"
// — currently used to reveal CSVDataSet rows that live below default depth.
watch(
  () => ctx?.forceExpandPaths.value,
  (paths) => {
    if (paths && paths.has(props.node.path)) expanded.value = true
  },
  { immediate: true },
)

const hasChildren = computed(() => props.node.children.length > 0)
const busy = computed(() => props.busyPaths.has(props.node.path))
const effectivelyActive = computed(
  () => props.node.enabled && (props.parentEnabled ?? true),
)

// ── Search highlight + auto-expand ancestors of matches ─────────────────
function nodeMatches(n: JmxComponent, q: string): boolean {
  if (!q) return false
  return n.testname.toLowerCase().includes(q) || n.tag.toLowerCase().includes(q)
}

function anyDescendantMatches(n: JmxComponent, q: string): boolean {
  for (const c of n.children) {
    if (nodeMatches(c, q) || anyDescendantMatches(c, q)) return true
  }
  return false
}

const searchQ = computed(() => (ctx?.searchQuery.value ?? '').trim().toLowerCase())

const isMatch = computed(() => nodeMatches(props.node, searchQ.value))
const hasMatchingDescendant = computed(
  () => !!searchQ.value && anyDescendantMatches(props.node, searchQ.value),
)

// When a search hits this node or any descendant, force this row's branch open
// so the user can see the match in context. Empty query = no-op (user-collapsed
// state is preserved).
watch([isMatch, hasMatchingDescendant], ([m, dm]) => {
  if (m || dm) expanded.value = true
})

// ── Expand / collapse all triggers ───────────────────────────────────────
watch(() => ctx?.expandTrigger.value, () => {
  // Mimic initial state: open depth 0/1/2, leave deeper alone to avoid
  // dumping the user into a wall of leaves.
  if (props.depth < 2) expanded.value = true
})
watch(() => ctx?.collapseTrigger.value, () => {
  // Keep TestPlan itself open (otherwise the toolbar becomes the only thing
  // visible, which is disorienting).
  if (props.depth > 0) expanded.value = false
})

function handleToggle() {
  if (busy.value || isRootTestPlan.value) return
  emit('toggle', props.node.path, !props.node.enabled)
}

function handleChevron() {
  if (hasChildren.value) expanded.value = !expanded.value
}

function fireExpandAll() {
  if (ctx) ctx.expandTrigger.value++
}
function fireCollapseAll() {
  if (ctx) ctx.collapseTrigger.value++
}

const isFlashing = computed(
  () => ctx?.errorFlashPath.value === props.node.path,
)

const rowBackground = computed(() => {
  // Error flash wins over search highlight so the user can't miss a failed save.
  if (isFlashing.value) {
    return props.isDark ? 'rgba(239,68,68,0.28)' : 'rgba(254,202,202,0.75)'
  }
  if (isMatch.value) {
    return props.isDark ? 'rgba(250,204,21,0.18)' : 'rgba(254,240,138,0.55)'
  }
  return 'transparent'
})

const toolbarBtnStyle = computed(() => ({
  background: props.isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.03)',
  color: props.isDark ? 'rgba(255,255,255,0.75)' : 'rgba(0,0,0,0.65)',
  border: `1px solid ${props.isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
}))
</script>

<template>
  <div>
    <!-- Row -->
    <div
      class="flex items-center gap-2 py-1.5 rounded-md transition-colors"
      :style="{
        paddingLeft: `${depth * 18 + 8}px`,
        paddingRight: '10px',
        opacity: effectivelyActive ? 1 : 0.45,
        background: rowBackground,
      }"
    >
      <!-- Chevron (placeholder kept for alignment when no children) -->
      <button
        class="w-4 h-4 flex items-center justify-center rounded-sm flex-shrink-0"
        :class="hasChildren ? 'cursor-pointer' : ''"
        :style="{ visibility: hasChildren ? 'visible' : 'hidden' }"
        @click="handleChevron"
      >
        <Motion
          as="div"
          :animate="{ rotate: expanded ? 90 : 0 }"
          :transition="{ duration: 0.15 }"
          class="flex"
        >
          <ChevronRight
            :size="14"
            :color="isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.4)'"
          />
        </Motion>
      </button>

      <!-- Status dot -->
      <div
        class="w-1.5 h-1.5 rounded-full flex-shrink-0 transition-colors"
        :style="{ background: node.enabled ? '#10b981' : '#64748b' }"
      />

      <!-- testname — 双击可编辑（TestPlan 根节点除外） -->
      <input
        v-if="isEditingName"
        ref="nameInput"
        v-model="editNameValue"
        class="text-[13px] px-1 py-0 rounded-sm outline-none min-w-[120px]"
        :style="{
          background: isDark ? 'rgba(59,130,246,0.1)' : 'rgba(59,130,246,0.08)',
          border: `1px solid ${isDark ? 'rgba(59,130,246,0.45)' : 'rgba(59,130,246,0.4)'}`,
          color: isDark ? '#fff' : '#1a1a2e',
        }"
        @blur="commitRename"
        @keyup.enter="commitRename"
        @keyup.esc="cancelRename"
        @click.stop
      />
      <span
        v-else
        class="text-[13px] truncate select-none"
        :class="!isRootTestPlan && isEditable ? 'cursor-pointer hover:underline' : !isRootTestPlan ? 'cursor-text' : ''"
        :style="{ color: isDark ? '#fff' : '#1a1a2e' }"
        :title="!isRootTestPlan ? (isEditable ? '点击编辑 / 双击改名' : '双击改名') : undefined"
        @click.stop="isEditable && !isRootTestPlan && emit('edit', node)"
        @dblclick.stop="startRename"
      >
        {{ node.testname || '(未命名)' }}
      </span>

      <!-- tag (muted mono) -->
      <span
        class="text-[11px] font-mono truncate"
        :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)' }"
      >
        {{ node.tag }}
      </span>

      <!-- spacer -->
      <div class="flex-1 min-w-2" />

      <!-- Right side: TestPlan → toolbar; others → enabled toggle -->
      <template v-if="isRootTestPlan">
        <div class="flex items-center gap-1.5 flex-shrink-0">
          <!-- Search -->
          <div class="relative">
            <Search
              :size="12"
              class="absolute left-2 top-1/2 -translate-y-1/2 pointer-events-none"
              :color="isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)'"
            />
            <input
              v-if="ctx"
              v-model="ctx.searchQuery.value"
              type="text"
              placeholder="搜索组件..."
              class="w-[180px] pl-7 pr-2 py-1 rounded-md text-[12px] outline-none"
              :style="{
                background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
                border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
                color: isDark ? '#fff' : '#1a1a2e',
              }"
            />
          </div>
          <button
            class="px-2 py-1 rounded-md text-[11px] flex items-center gap-1 cursor-pointer"
            :style="toolbarBtnStyle"
            @click="fireExpandAll"
          >
            <ChevronsDownUp :size="11" />
            全部展开
          </button>
          <button
            class="px-2 py-1 rounded-md text-[11px] flex items-center gap-1 cursor-pointer"
            :style="toolbarBtnStyle"
            @click="fireCollapseAll"
          >
            <ChevronsUpDown :size="11" />
            全部折叠
          </button>
        </div>
      </template>

      <template v-else>
        <!-- CSV inline upload (only on <CSVDataSet> rows) -->
        <template v-if="isCsvDataSet">
          <input
            ref="csvInput"
            type="file"
            accept=".csv"
            class="hidden"
            @change="onCsvPick"
          />
          <button
            class="w-7 h-5 rounded-md flex items-center justify-center flex-shrink-0 mr-1.5 transition-colors"
            :title="csvBinding ? `当前 CSV: ${csvBinding.filename}（点击替换）` : '上传 CSV 参数化文件'"
            :style="{
              background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)',
              border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
              cursor: csvUploading ? 'wait' : 'pointer',
              opacity: csvUploading ? 0.6 : 1,
              color: csvBinding
                ? '#10b981'
                : isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.6)',
            }"
            :disabled="csvUploading"
            @click="csvInput?.click()"
          >
            <Paperclip :size="11" />
          </button>
        </template>

        <!-- JAR inline upload (only on BeanShellPreProcessor rows) -->
        <template v-if="isBeanShellPre">
          <input
            ref="jarInput"
            type="file"
            accept=".jar"
            class="hidden"
            @change="onJarPick"
          />
          <button
            class="w-7 h-5 rounded-md flex items-center justify-center flex-shrink-0 mr-1.5 transition-colors"
            title="上传 JAR 到 JMeter lib/ext/"
            :style="{
              background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)',
              border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
              cursor: jarUploading ? 'wait' : 'pointer',
              opacity: jarUploading ? 0.6 : 1,
              color: isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.6)',
            }"
            :disabled="jarUploading"
            @click.stop="jarInput?.click()"
          >
            <Package :size="11" />
          </button>
        </template>

        <!-- enabled toggle -->
        <button
          class="relative w-9 h-5 rounded-full transition-colors flex-shrink-0 cursor-pointer"
          :disabled="busy"
          :style="{
            background: node.enabled
              ? '#10b981'
              : isDark ? 'rgba(255,255,255,0.14)' : 'rgba(0,0,0,0.14)',
            opacity: busy ? 0.6 : 1,
            cursor: busy ? 'wait' : 'pointer',
          }"
          @click="handleToggle"
        >
          <div
            class="absolute top-[2px] w-4 h-4 rounded-full bg-white transition-all duration-200"
            :style="{
              left: node.enabled ? '18px' : '2px',
              boxShadow: '0 1px 3px rgba(0,0,0,0.25)',
            }"
          />
        </button>
      </template>
    </div>

    <!-- Children -->
    <div v-if="expanded && hasChildren">
      <ComponentNode
        v-for="c in node.children"
        :key="c.path"
        :node="c"
        :depth="depth + 1"
        :is-dark="isDark"
        :busy-paths="busyPaths"
        :parent-enabled="effectivelyActive"
        @toggle="(p, n) => emit('toggle', p, n)"
        @rename="(p, name) => emit('rename', p, name)"
        @edit="(n) => emit('edit', n)"
      />
    </div>
  </div>
</template>
