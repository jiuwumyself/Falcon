<script setup lang="ts">
import { ref, watch, computed, provide, toRef } from 'vue'
import { Motion } from 'motion-v'
import { Loader, AlertCircle } from 'lucide-vue-next'
import { api, ApiError, tasksApi } from '@/lib/api'
import type { Task, JmxComponent } from '@/types/task'
import ComponentNode from './ComponentNode.vue'
import DetailDrawer from './DetailDrawer.vue'
import { SCRIPT_TREE_CTX, type ScriptTreeCtx } from './scriptTreeCtx'

const props = defineProps<{ task: Task; isDark?: boolean }>()
const emit = defineEmits<{ (e: 'task-updated', task: Task): void }>()

const tree = ref<JmxComponent[]>([])
const loading = ref(false)
const error = ref('')
const busyPaths = ref<Set<string>>(new Set())

// Tree-wide shared state
const searchQuery = ref('')
const expandTrigger = ref(0)
const collapseTrigger = ref(0)
const errorFlashPath = ref<string | null>(null)
const forceExpandPaths = ref<Set<string>>(new Set())
const editingNode = ref<JmxComponent | null>(null)
// 编辑节点是否在启用的祖先链下；false 时 DetailDrawer 顶部显示警告条
const editingNodeEffective = ref(true)

/**
 * 走索引路径检查祖先链：path "0.4.4" → tree[0] → children[4] → children[4]，
 * 每一层 enabled 都为 true 才返回 true。任一环节禁用即返 false。
 */
function effectiveEnabledByPath(path: string): boolean {
  if (!tree.value.length) return true  // tree 还没加载，给默认值，避免误报警告
  const segs = path.split('.').map((s) => parseInt(s, 10))
  if (segs.length === 0 || isNaN(segs[0])) return true
  let cur: JmxComponent | undefined = tree.value[segs[0]]
  if (!cur || !cur.enabled) return false
  for (let i = 1; i < segs.length; i++) {
    const idx = segs[i]
    if (isNaN(idx)) return false
    cur = cur.children[idx]
    if (!cur || !cur.enabled) return false
  }
  return true
}

function handleEdit(node: JmxComponent) {
  editingNode.value = node
  editingNodeEffective.value = effectiveEnabledByPath(node.path)
}

async function uploadCsv(componentPath: string, file: File): Promise<Task> {
  const updated = await tasksApi.uploadComponentCsv(props.task.id, componentPath, file)
  emit('task-updated', updated)
  return updated
}

async function uploadJar(_componentPath: string, file: File): Promise<void> {
  const fd = new FormData()
  fd.append('jar_file', file)
  await api(`/tasks/${props.task.id}/components/upload-jar/`, { method: 'POST', body: fd })
}

const ctx: ScriptTreeCtx = {
  searchQuery,
  expandTrigger,
  collapseTrigger,
  errorFlashPath,
  forceExpandPaths,
  task: toRef(props, 'task'),
  uploadCsv,
  uploadJar,
}
provide(SCRIPT_TREE_CTX, ctx)

async function load() {
  loading.value = true
  error.value = ''
  try {
    tree.value = await api<JmxComponent[]>(`/tasks/${props.task.id}/components/`)
  } catch (e) {
    error.value = e instanceof ApiError ? e.humanMessage : String(e)
  } finally {
    loading.value = false
  }
}

async function handleRename(path: string, testname: string) {
  busyPaths.value = new Set([...busyPaths.value, path])
  try {
    const updated = await api<JmxComponent[]>(
      `/tasks/${props.task.id}/components/rename/`,
      {
        method: 'POST',
        body: JSON.stringify({ path, testname }),
      },
    )
    tree.value = updated
    error.value = ''
  } catch (e) {
    error.value = e instanceof ApiError ? e.humanMessage : String(e)
    errorFlashPath.value = path
    setTimeout(() => {
      if (errorFlashPath.value === path) errorFlashPath.value = null
    }, 800)
  } finally {
    const nextSet = new Set(busyPaths.value)
    nextSet.delete(path)
    busyPaths.value = nextSet
  }
}

async function handleToggle(path: string, next: boolean) {
  busyPaths.value = new Set([...busyPaths.value, path])
  try {
    const updated = await api<JmxComponent[]>(
      `/tasks/${props.task.id}/components/toggle/`,
      {
        method: 'POST',
        body: JSON.stringify({ path, enabled: next }),
      },
    )
    tree.value = updated
    error.value = ''
  } catch (e) {
    error.value = e instanceof ApiError ? e.humanMessage : String(e)
    // Flash the failing row red for 800 ms so the user notices the save didn't go through.
    errorFlashPath.value = path
    setTimeout(() => {
      if (errorFlashPath.value === path) errorFlashPath.value = null
    }, 800)
  } finally {
    const nextSet = new Set(busyPaths.value)
    nextSet.delete(path)
    busyPaths.value = nextSet
  }
}

// After every tree reload, recompute the set of paths that should be forced
// open: every <CSVDataSet> and all its ancestors, so the user can always
// reach its inline upload icon regardless of default depth limits.
function collectCsvPaths(nodes: JmxComponent[], acc: Set<string>) {
  for (const n of nodes) {
    if (n.tag === 'CSVDataSet') {
      // add self + walk ancestor path prefixes (e.g. "0.2.1" → "0", "0.2")
      const segs = n.path.split('.')
      for (let i = 1; i <= segs.length; i++) {
        acc.add(segs.slice(0, i).join('.'))
      }
    }
    if (n.children.length) collectCsvPaths(n.children, acc)
  }
}

watch(tree, (t) => {
  const paths = new Set<string>()
  collectCsvPaths(t, paths)
  forceExpandPaths.value = paths
}, { deep: true })

// Watch id + jmx_hash: id changes on new task; hash changes on "replace-jmx" overwrite.
watch(() => [props.task.id, props.task.jmx_hash], load, { immediate: true })

const isEmpty = computed(() => !loading.value && tree.value.length === 0)
</script>

<template>
  <div>
    <p
      v-if="error"
      class="text-[12px] text-red-500 mb-2 flex items-center gap-1"
    >
      <AlertCircle :size="12" /> {{ error }}
    </p>

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
      加载组件树…
    </div>

    <p
      v-else-if="isEmpty"
      class="text-[12px] py-6 text-center"
      :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }"
    >
      没有解析到任何组件
    </p>

    <div
      v-else
      class="rounded-lg py-2"
      :style="{
        background: isDark ? 'rgba(255,255,255,0.015)' : 'rgba(0,0,0,0.015)',
        border: `1px solid ${isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)'}`,
      }"
    >
      <ComponentNode
        v-for="n in tree"
        :key="n.path"
        :node="n"
        :depth="0"
        :is-dark="!!isDark"
        :busy-paths="busyPaths"
        @toggle="handleToggle"
        @rename="handleRename"
        @edit="handleEdit"
      />
    </div>

    <DetailDrawer
      :node="editingNode"
      :task-id="task.id"
      :is-dark="!!isDark"
      :effective-enabled="editingNodeEffective"
      @close="editingNode = null"
      @saved="tree = $event"
    />
  </div>
</template>
