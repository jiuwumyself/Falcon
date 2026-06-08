<script setup lang="ts">
// Pinpoint 诊断区块：Transactions / Top Exceptions / 慢URL / Active Threads / DataSource / Arthas。
import { computed, ref } from 'vue'
import { Activity, AlertTriangle, Timer, Cpu, Database, Terminal, ExternalLink, MemoryStick } from 'lucide-vue-next'
import type { DiagnosisResponse } from '@/types/task'

const props = defineProps<{ data: DiagnosisResponse | null; isDark: boolean }>()
const d = (l: string, dk: string) => (props.isDark ? dk : l)
const card = computed(() => ({
  background: props.isDark ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.6)',
  border: `1px solid ${props.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
}))

const tx = computed(() => props.data?.transactions)
const histMax = computed(() => Math.max(1, ...(tx.value?.histogram || []).map((h) => h.count)))
const histColor = (label: string) =>
  label === '错误' ? '#ef4444' : label === '>5s' ? '#d85a30' : label === '3~5s' ? '#ef9f27'
    : label === '1~3s' ? '#97c459' : '#1d9e75'

const exceptions = computed(() => props.data?.exceptions || [])
const uris = computed(() => props.data?.uri_stat || [])
const at = computed(() => props.data?.active_threads)
const ds = computed(() => props.data?.datasource)
const agents = computed(() => props.data?.agents || [])
const selectedAgent = ref('')

const serverMapUrl = computed(() => props.data?.pinpoint_base_url || '')
const stripPkg = (s: string) => s.split('.').pop() || s
const fmtMs = (v: number) => (v >= 1000 ? (v / 1000).toFixed(2) + 's' : v.toFixed(0) + 'ms')

// ── JVM（Pinpoint inspector，应用级）──
const jvm = computed(() => props.data?.jvm)
const heap = computed(() => jvm.value?.heap)
const nonHeap = computed(() => jvm.value?.non_heap)
const threads = computed(() => jvm.value?.threads)
const loadedClass = computed(() => jvm.value?.loaded_class)
const gc = computed(() => jvm.value?.gc)
const hasJvm = computed(() => !!(heap.value?.series?.length || threads.value?.last || loadedClass.value?.last))
const fmtBytes = (v: number) => {
  if (v >= 1073741824) return (v / 1073741824).toFixed(2) + 'G'
  if (v >= 1048576) return (v / 1048576).toFixed(0) + 'M'
  if (v >= 1024) return (v / 1024).toFixed(0) + 'K'
  return v.toFixed(0) + 'B'
}
const fmtNum = (v: number) => (v >= 1000 ? (v / 1000).toFixed(1) + 'k' : v.toFixed(0))
const HEAP_W = 320, HEAP_H = 46
// y 轴自适应到 heap 自己的 [min,max]（带 10% padding）→ 锯齿/涨落看得清，而非贴顶平直
const heapRange = computed<[number, number]>(() => {
  const s = heap.value?.series
  if (!s || s.length < 2) return [0, 1]
  const ys = s.map((p) => p[1])
  let lo = Math.min(...ys), hi = Math.max(...ys)
  if (hi <= lo) hi = lo + 1
  const pad = (hi - lo) * 0.1
  return [lo - pad, hi + pad]
})
const heapPath = computed(() => {
  const s = heap.value?.series
  if (!s || s.length < 2) return ''
  const xs = s.map((p) => p[0])
  const xmin = Math.min(...xs), xr = (Math.max(...xs) - xmin) || 1
  const [lo, hi] = heapRange.value, span = (hi - lo) || 1
  return s.map((p, i) =>
    `${i === 0 ? 'M' : 'L'}${((p[0] - xmin) / xr * HEAP_W).toFixed(1)},${(HEAP_H - (p[1] - lo) / span * HEAP_H).toFixed(1)}`,
  ).join(' ')
})
</script>

<template>
  <div class="flex flex-col gap-3">
    <!-- 行1：Transactions + Top Exceptions -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
      <!-- Transactions -->
      <div class="rounded-xl p-3" :style="card">
        <div class="flex items-center gap-2 mb-2">
          <Activity :size="13" :color="'#0c447c'" />
          <span class="text-[13px] font-medium" :style="{ color: d('rgba(0,0,0,0.7)', 'rgba(255,255,255,0.75)') }">Transactions</span>
          <span class="text-[10px] px-1.5 py-0.5 rounded-md" :style="{ color: '#0c447c', background: d('#e6f1fb', 'rgba(59,130,246,0.14)') }">Pinpoint</span>
        </div>
        <div v-if="tx" class="flex gap-5 mb-3">
          <div><p class="text-[11px] m-0" :style="{ color: d('rgba(0,0,0,0.5)', 'rgba(255,255,255,0.5)') }">TPS</p><p class="text-[18px] font-medium m-0" :style="{ color: d('#1a1a2e', '#fff') }">{{ tx.tps }}</p></div>
          <div><p class="text-[11px] m-0" :style="{ color: d('rgba(0,0,0,0.5)', 'rgba(255,255,255,0.5)') }">总请求</p><p class="text-[18px] font-medium m-0" :style="{ color: d('#1a1a2e', '#fff') }">{{ tx.total.toLocaleString() }}</p></div>
          <div><p class="text-[11px] m-0" :style="{ color: d('rgba(0,0,0,0.5)', 'rgba(255,255,255,0.5)') }">错误率</p><p class="text-[18px] font-medium m-0" :style="{ color: tx.error_rate > 0 ? '#ef4444' : '#10b981' }">{{ tx.error_rate }}%</p></div>
          <div><p class="text-[11px] m-0" :style="{ color: d('rgba(0,0,0,0.5)', 'rgba(255,255,255,0.5)') }">均/峰延迟</p><p class="text-[18px] font-medium m-0" :style="{ color: d('#1a1a2e', '#fff') }">{{ tx.avg_ms }}/{{ tx.max_ms }}ms</p></div>
        </div>
        <div v-if="tx" class="flex flex-col gap-1">
          <div v-for="h in tx.histogram" :key="h.label" class="flex items-center gap-1.5">
            <span class="text-[10px] w-9" :style="{ color: d('rgba(0,0,0,0.5)', 'rgba(255,255,255,0.5)') }">{{ h.label }}</span>
            <div class="flex-1 h-[7px] rounded" :style="{ background: d('rgba(0,0,0,0.05)', 'rgba(255,255,255,0.06)') }">
              <div class="h-full rounded" :style="{ width: (h.count / histMax * 100) + '%', background: histColor(h.label) }" />
            </div>
            <span class="text-[10px] w-12 text-right tabular-nums" :style="{ color: d('rgba(0,0,0,0.6)', 'rgba(255,255,255,0.6)') }">{{ h.count.toLocaleString() }}</span>
          </div>
        </div>
        <p v-else class="text-[11px] py-3 text-center" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">无事务数据</p>
      </div>

      <!-- Top Exceptions -->
      <div class="rounded-xl p-3" :style="card">
        <div class="flex items-center gap-2 mb-2">
          <AlertTriangle :size="13" :color="'#a32d2d'" />
          <span class="text-[13px] font-medium" :style="{ color: d('rgba(0,0,0,0.7)', 'rgba(255,255,255,0.75)') }">Top Exceptions</span>
        </div>
        <div v-if="exceptions.length" class="flex flex-col gap-2">
          <div v-for="(e, i) in exceptions" :key="i" class="flex items-center gap-2">
            <AlertTriangle :size="13" :color="i === 0 ? '#ef4444' : '#f59e0b'" />
            <span class="flex-1 text-[12px] truncate" :title="e.exception_class" :style="{ color: d('rgba(0,0,0,0.8)', 'rgba(255,255,255,0.85)') }">{{ stripPkg(e.exception_class) }}</span>
            <span class="text-[12px] font-medium tabular-nums" :style="{ color: '#ef4444' }">×{{ e.count }}</span>
          </div>
        </div>
        <p v-else class="text-[11px] py-5 text-center" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">本时段无异常 🎉</p>
      </div>
    </div>

    <!-- 慢 URL -->
    <div class="rounded-xl p-3" :style="card">
      <div class="flex items-center gap-2 mb-2">
        <Timer :size="13" :color="'#0c447c'" />
        <span class="text-[13px] font-medium" :style="{ color: d('rgba(0,0,0,0.7)', 'rgba(255,255,255,0.75)') }">慢 URL · top {{ uris.length }}</span>
        <span class="text-[10px] px-1.5 py-0.5 rounded-md" :style="{ color: '#0c447c', background: d('#e6f1fb', 'rgba(59,130,246,0.14)') }">UriStat</span>
      </div>
      <div v-if="uris.length" class="flex flex-col gap-1.5">
        <div v-for="(u, i) in uris" :key="i" class="flex items-center gap-2">
          <span class="w-1.5 h-1.5 rounded-full flex-shrink-0" :style="{ background: u.avg_ms >= 1000 ? '#e24b4a' : u.avg_ms >= 300 ? '#ba7517' : '#1d9e75' }" />
          <span class="flex-1 text-[12px] truncate" :title="u.uri" :style="{ color: d('rgba(0,0,0,0.8)', 'rgba(255,255,255,0.85)') }">{{ u.uri }}</span>
          <span class="text-[12px] font-medium w-16 text-right tabular-nums" :style="{ color: u.avg_ms >= 1000 ? '#ef4444' : d('#1a1a2e', '#fff') }">{{ fmtMs(u.avg_ms) }}</span>
          <span class="text-[11px] w-12 text-right tabular-nums" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">{{ u.count.toLocaleString() }}</span>
        </div>
      </div>
      <p v-else class="text-[11px] py-3 text-center" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">无 URL 统计</p>
    </div>

    <!-- 行3：Active Threads + DataSource -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
      <div class="rounded-xl p-3" :style="card">
        <div class="flex items-center gap-2 mb-2">
          <Cpu :size="13" :color="'#806eb7'" />
          <span class="text-[13px] font-medium" :style="{ color: d('rgba(0,0,0,0.7)', 'rgba(255,255,255,0.75)') }">Active Threads</span>
        </div>
        <p v-if="at" class="text-[20px] font-medium m-0" :style="{ color: d('#1a1a2e', '#fff') }">
          {{ at.max }} <span class="text-[12px] font-normal" :style="{ color: d('rgba(0,0,0,0.5)', 'rgba(255,255,255,0.5)') }">峰值 · 均 {{ at.avg }} 活跃请求</span>
        </p>
        <p v-else class="text-[11px] py-2" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">无活跃线程数据</p>
      </div>
      <div class="rounded-xl p-3" :style="card">
        <div class="flex items-center gap-2 mb-2">
          <Database :size="13" :color="'#0f6e56'" />
          <span class="text-[13px] font-medium" :style="{ color: d('rgba(0,0,0,0.7)', 'rgba(255,255,255,0.75)') }">DataSource 连接</span>
        </div>
        <p v-if="ds" class="text-[20px] font-medium m-0" :style="{ color: d('#1a1a2e', '#fff') }">
          {{ ds.max }} <span class="text-[12px] font-normal" :style="{ color: d('rgba(0,0,0,0.5)', 'rgba(255,255,255,0.5)') }">峰值 · 均 {{ ds.avg }} 活跃连接</span>
        </p>
        <p v-else class="text-[11px] py-2" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">无连接池数据</p>
      </div>
    </div>

    <!-- JVM（Pinpoint inspector：堆内存 + 线程 + 类加载；CPU 见 Pod 时序，GC 这版应用级无） -->
    <div v-if="hasJvm" class="rounded-xl p-3" :style="card">
      <div class="flex items-center gap-2 mb-2">
        <MemoryStick :size="13" :color="'#b45309'" />
        <span class="text-[13px] font-medium" :style="{ color: d('rgba(0,0,0,0.7)', 'rgba(255,255,255,0.75)') }">JVM</span>
        <span class="text-[10px] px-1.5 py-0.5 rounded-md" :style="{ color: '#0c447c', background: d('#e6f1fb', 'rgba(59,130,246,0.14)') }">Pinpoint</span>
      </div>
      <div class="flex gap-6 mb-2 flex-wrap">
        <div><p class="text-[11px] m-0" :style="{ color: d('rgba(0,0,0,0.5)', 'rgba(255,255,255,0.5)') }">堆内存峰值</p><p class="text-[18px] font-medium m-0" :style="{ color: d('#1a1a2e', '#fff') }">{{ heap ? fmtBytes(heap.max) : '—' }} <span class="text-[11px] font-normal" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">均 {{ heap ? fmtBytes(heap.avg) : '—' }}</span></p></div>
        <div><p class="text-[11px] m-0" :style="{ color: d('rgba(0,0,0,0.5)', 'rgba(255,255,255,0.5)') }">Non-Heap</p><p class="text-[18px] font-medium m-0" :style="{ color: d('#1a1a2e', '#fff') }">{{ nonHeap ? fmtBytes(nonHeap.max) : '—' }} <span class="text-[11px] font-normal" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">峰</span></p></div>
        <div><p class="text-[11px] m-0" :style="{ color: d('rgba(0,0,0,0.5)', 'rgba(255,255,255,0.5)') }">线程数</p><p class="text-[18px] font-medium m-0" :style="{ color: d('#1a1a2e', '#fff') }">{{ threads ? threads.max : '—' }} <span class="text-[11px] font-normal" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">峰 · 均 {{ threads ? threads.avg : '—' }}</span></p></div>
        <div><p class="text-[11px] m-0" :style="{ color: d('rgba(0,0,0,0.5)', 'rgba(255,255,255,0.5)') }">类加载</p><p class="text-[18px] font-medium m-0" :style="{ color: d('#1a1a2e', '#fff') }">{{ loadedClass ? fmtNum(loadedClass.last) : '—' }}</p></div>
        <div><p class="text-[11px] m-0" :style="{ color: d('rgba(0,0,0,0.5)', 'rgba(255,255,255,0.5)') }">Old GC</p><p class="text-[18px] font-medium m-0" :style="{ color: gc && gc.old_count > 0 ? '#f59e0b' : d('#1a1a2e', '#fff') }">{{ gc ? gc.old_count : '—' }} <span class="text-[11px] font-normal" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">{{ gc ? '次 · ' + gc.old_time_ms + 'ms' : '' }}</span></p></div>
      </div>
      <div v-if="heapPath" class="relative">
        <span class="absolute left-0 top-0 text-[9px]" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">{{ fmtBytes(heapRange[1]) }}</span>
        <span class="absolute left-0 bottom-0 text-[9px]" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">{{ fmtBytes(heapRange[0]) }}</span>
        <svg :viewBox="`0 0 ${HEAP_W} ${HEAP_H}`" preserveAspectRatio="none" class="w-full h-[52px]">
          <path :d="heapPath" fill="none" stroke="#f59e0b" stroke-width="1.6" vector-effect="non-scaling-stroke" />
        </svg>
        <p class="text-[10px] mt-0.5" :style="{ color: d('rgba(0,0,0,0.45)', 'rgba(255,255,255,0.45)') }">堆内存使用趋势（纵轴自适应区间，看 GC 涨落）</p>
      </div>
    </div>

    <!-- Arthas 入口（占位） -->
    <div class="flex items-center gap-3 flex-wrap p-3 rounded-xl" :style="{ background: d('rgba(0,0,0,0.03)', 'rgba(255,255,255,0.03)') }">
      <span class="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0" style="background:#0f6e56">
        <Terminal :size="15" color="#fff" />
      </span>
      <div class="flex-1 min-w-[120px]">
        <p class="text-[13px] font-medium m-0" :style="{ color: d('#1a1a2e', '#fff') }">Arthas · 未连接</p>
        <p class="text-[11px] m-0" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">attach 会暂停目标 JVM 数百毫秒，按需开启（tunnel 待接入）</p>
      </div>
      <select v-model="selectedAgent" class="text-[12px] max-w-[200px] rounded-md px-2 py-1"
              :style="{ background: d('rgba(255,255,255,0.7)', 'rgba(255,255,255,0.06)'), color: d('#1a1a2e', '#eee'), border: `1px solid ${d('rgba(0,0,0,0.1)', 'rgba(255,255,255,0.1)')}` }">
        <option value="">{{ agents.length ? '选择 agent' : '无可用 agent' }}</option>
        <option v-for="a in agents" :key="a.agent_id" :value="a.agent_id">{{ a.agent_name }}</option>
      </select>
      <button disabled class="text-[12px] px-3 py-1 rounded-md inline-flex items-center gap-1 opacity-50 cursor-not-allowed"
              :style="{ border: `1px solid ${d('rgba(0,0,0,0.15)', 'rgba(255,255,255,0.15)')}`, color: d('rgba(0,0,0,0.5)', 'rgba(255,255,255,0.5)') }"
              title="需接入 Arthas tunnel（后续立项）">
        <Terminal :size="12" />连接 Arthas
      </button>
      <a v-if="serverMapUrl" :href="serverMapUrl" target="_blank" rel="noopener"
         class="text-[11px] text-blue-500 hover:underline inline-flex items-center gap-0.5">Pinpoint <ExternalLink :size="11" /></a>
    </div>
  </div>
</template>
