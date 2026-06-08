<script setup lang="ts">
// Pod 时序：维度切换(CPU/内存/网络/磁盘) + per-pod 多线 + Mean/Max 表。
// cpu/mem 走 per-pod；net/disk 走聚合(接收/发送、读/写)。数据来自 Prometheus。
import { computed, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { Cpu, Database, Network, HardDrive, Loader, Maximize2, X } from 'lucide-vue-next'
import type { PrometheusMetricsResponse } from '@/types/task'
import { computeStats, makeLineOption, podsToSeries, seriesFrom, type NamedSeries } from './podChartFactory'

use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  data: PrometheusMetricsResponse | null
  loading: boolean
  isDark: boolean
}>()

type Dim = 'cpu' | 'mem' | 'net' | 'disk'
const dim = ref<Dim>('cpu')
const DIMS: { id: Dim; label: string; icon: any; unit: string }[] = [
  { id: 'cpu', label: 'CPU', icon: Cpu, unit: '%' },
  { id: 'mem', label: '内存', icon: Database, unit: '%' },
  { id: 'net', label: '网络', icon: Network, unit: ' KB/s' },
  { id: 'disk', label: '磁盘', icon: HardDrive, unit: ' KB/s' },
]
const unitOf = (dd: Dim) => DIMS.find((d) => d.id === dd)!.unit
const curUnit = computed(() => unitOf(dim.value))

function seriesForDim(dd: Dim): NamedSeries[] {
  const m = props.data
  if (!m) return []
  if (dd === 'cpu') return podsToSeries(m.cpu_usage_by_pod?.pods)
  if (dd === 'mem') return podsToSeries(m.memory_usage_by_pod?.pods)
  if (dd === 'net') {
    return [seriesFrom(m.network_rx, '接收', '#3b82f6'), seriesFrom(m.network_tx, '发送', '#a855f7')]
      .filter((s): s is NamedSeries => !!s)
  }
  return [seriesFrom(m.disk_read, '读取', '#10b981'), seriesFrom(m.disk_write, '写入', '#f59e0b')]
    .filter((s): s is NamedSeries => !!s)
}
function rowsForDim(dd: Dim) {
  return seriesForDim(dd).map((s) => {
    const st = computeStats(s.data)
    const parts = s.name.split('-')   // pod 名取尾段短名
    const short = parts.length > 2 ? parts[parts.length - 1] : s.name
    return { name: short, full: s.name, color: s.color, mean: st.mean, max: st.max }
  })
}

const series = computed<NamedSeries[]>(() => seriesForDim(dim.value))
const option = computed(() => makeLineOption(series.value, curUnit.value, props.isDark))
const rows = computed(() => rowsForDim(dim.value))

// 扩展弹窗：一次看全部 4 个维度
const showAll = ref(false)
const allPanels = computed(() => DIMS.map((d) => {
  const s = seriesForDim(d.id)
  return { ...d, series: s, option: makeLineOption(s, d.unit, props.isDark), rows: rowsForDim(d.id) }
}))

const dim2 = (l: string, d: string) => (props.isDark ? d : l)
const fmt = (v: number) => (v >= 100 ? v.toFixed(0) : v.toFixed(1))
</script>

<template>
  <div class="rounded-xl p-3" :style="{
    background: dim2('rgba(255,255,255,0.6)', 'rgba(255,255,255,0.02)'),
    border: `1px solid ${dim2('rgba(0,0,0,0.06)', 'rgba(255,255,255,0.06)')}`,
  }">
    <div class="flex items-center gap-2 mb-2 flex-wrap">
      <span class="text-[13px] font-medium" :style="{ color: dim2('rgba(0,0,0,0.7)', 'rgba(255,255,255,0.75)') }">Pod 时序</span>
      <span class="text-[10px] px-1.5 py-0.5 rounded-md" :style="{ color: '#0f6e56', background: dim2('#e1f5ee', 'rgba(16,185,129,0.12)') }">Prometheus</span>
      <Loader v-if="loading" :size="11" class="animate-spin opacity-60" />
      <span class="flex-1" />
      <button v-for="d in DIMS" :key="d.id"
              class="inline-flex items-center gap-1 text-[12px] px-2.5 py-1 rounded-md transition"
              :style="{
                background: dim === d.id ? dim2('rgba(0,0,0,0.06)', 'rgba(255,255,255,0.1)') : 'transparent',
                color: dim === d.id ? dim2('#1a1a2e', '#fff') : dim2('rgba(0,0,0,0.5)', 'rgba(255,255,255,0.5)'),
              }"
              @click="dim = d.id">
        <component :is="d.icon" :size="13" />{{ d.label }}
      </button>
      <button class="inline-flex items-center justify-center w-7 h-7 rounded-md transition ml-1"
              :style="{ color: dim2('rgba(0,0,0,0.5)', 'rgba(255,255,255,0.5)') }"
              title="展开：同时看 CPU/内存/网络/磁盘" @click="showAll = true">
        <Maximize2 :size="14" />
      </button>
    </div>

    <div class="flex gap-3 items-stretch">
      <div class="flex-1 min-w-0">
        <VChart v-if="series.length" :option="option" autoresize style="width:100%;height:150px" />
        <p v-else class="text-[11px] py-10 text-center" :style="{ color: dim2('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">
          无 {{ DIMS.find(d => d.id === dim)?.label }} 数据
        </p>
      </div>
      <div class="w-[150px] flex-shrink-0 text-[11px] tabular-nums">
        <div class="flex text-[10px] mb-1" :style="{ color: dim2('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">
          <span class="flex-1" /><span class="w-10 text-right">Mean</span><span class="w-10 text-right">Max</span>
        </div>
        <div v-for="r in rows" :key="r.full" class="flex items-center mb-1" :title="r.full"
             :style="{ color: dim2('rgba(0,0,0,0.8)', 'rgba(255,255,255,0.85)') }">
          <span class="w-2 h-2 rounded-full mr-1.5 flex-shrink-0" :style="{ background: r.color }" />
          <span class="flex-1 truncate">{{ r.name }}</span>
          <span class="w-10 text-right">{{ fmt(r.mean) }}</span>
          <span class="w-10 text-right" :style="{ color: r.max >= 90 && curUnit === '%' ? '#ef4444' : 'inherit' }">{{ fmt(r.max) }}</span>
        </div>
      </div>
    </div>

    <!-- 扩展弹窗：2×2 同时看四个维度 -->
    <Teleport to="body">
      <div v-if="showAll" class="fixed inset-0 z-[60] flex items-center justify-center p-4 sm:p-8"
           style="background:rgba(0,0,0,0.55)" @click.self="showAll = false">
        <div class="rounded-2xl w-full max-w-5xl max-h-[90vh] overflow-y-auto p-5"
             :style="{ background: dim2('#ffffff', '#0f1622'), border: `1px solid ${dim2('rgba(0,0,0,0.08)','rgba(255,255,255,0.1)')}` }">
          <div class="flex items-center gap-2 mb-3">
            <span class="text-[14px] font-medium" :style="{ color: dim2('#1a1a2e', '#fff') }">Pod 时序 · 全部维度</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded-md" :style="{ color: '#0f6e56', background: dim2('#e1f5ee', 'rgba(16,185,129,0.12)') }">Prometheus</span>
            <span class="flex-1" />
            <button class="w-7 h-7 rounded-md inline-flex items-center justify-center"
                    :style="{ color: dim2('rgba(0,0,0,0.55)', 'rgba(255,255,255,0.6)') }" @click="showAll = false">
              <X :size="18" />
            </button>
          </div>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div v-for="p in allPanels" :key="p.id" class="rounded-xl p-3"
                 :style="{ background: dim2('rgba(0,0,0,0.02)', 'rgba(255,255,255,0.03)'), border: `1px solid ${dim2('rgba(0,0,0,0.05)','rgba(255,255,255,0.06)')}` }">
              <div class="flex items-center gap-1.5 mb-2" :style="{ color: dim2('rgba(0,0,0,0.7)', 'rgba(255,255,255,0.78)') }">
                <component :is="p.icon" :size="14" /><span class="text-[12px] font-medium">{{ p.label }}</span>
              </div>
              <VChart v-if="p.series.length" :option="p.option" autoresize style="width:100%;height:230px" />
              <p v-else class="text-[11px] py-12 text-center" :style="{ color: dim2('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">无 {{ p.label }} 数据</p>
              <div v-if="p.rows.length" class="flex flex-wrap gap-x-3 gap-y-0.5 mt-1.5 text-[10px] tabular-nums">
                <span v-for="r in p.rows" :key="r.full" class="inline-flex items-center" :title="r.full"
                      :style="{ color: dim2('rgba(0,0,0,0.7)', 'rgba(255,255,255,0.7)') }">
                  <span class="w-2 h-2 rounded-full mr-1" :style="{ background: r.color }" />
                  {{ r.name }} · {{ fmt(r.mean) }}/{{ fmt(r.max) }}{{ p.unit.trim() || '' }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
