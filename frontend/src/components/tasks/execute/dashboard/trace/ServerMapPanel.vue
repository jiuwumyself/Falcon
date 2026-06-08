<script setup lang="ts">
// Pinpoint serverMap 服务拓扑：上=ECharts 力导拓扑图，下=依赖调用表。
// 数据来自后端 /runs/:id/pinpoint-servermap/（按 run 时段从 Pinpoint 拉、合并）。
import { computed, ref, watchEffect } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { ExternalLink } from 'lucide-vue-next'
import type { ServerMapResponse, ServerMapNode, ServerMapLink } from '@/types/task'

use([GraphChart, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  data: ServerMapResponse
  isDark: boolean
  focusName?: string         // 中心服务名（有则按「左上游/中心/右下游」有向布局）
}>()

const dim = (light: string, dark: string) => (props.isDark ? dark : light)
const stripType = (key: string) => key.split('^')[0]

// 居中有向布局：本次服务居中，「直连」的主要调用方在左、被调在右（各取调用量 top N）。
// 嵌入式小面板放不下深度2全部上百节点，只画中心一圈最相关的；完整图点「在 Pinpoint 打开」。
const TOP_N = 12
const layout = computed(() => {
  const nodes = props.data.nodes
  const links = props.data.links
  const byKey = new Map(nodes.map((n) => [n.key, n]))
  const focusKey = (props.focusName && nodes.find((n) => n.name === props.focusName)?.key)
    || nodes.reduce((a, b) => (b.total_count > (a?.total_count ?? -1) ? b : a), nodes[0])?.key
  // 直连边：到中心的=调用方(左)，从中心出的=被调(右)
  const inLinks = links.filter((l) => l.to === focusKey).sort((a, b) => b.total_count - a.total_count).slice(0, TOP_N)
  const outLinks = links.filter((l) => l.from === focusKey).sort((a, b) => b.total_count - a.total_count).slice(0, TOP_N)
  const callers = inLinks.map((l) => l.from)
  const callees = outLinks.map((l) => l.to)
  const visibleKeys = new Set<string>([focusKey, ...callers, ...callees].filter(Boolean) as string[])
  const visibleLinks = [...inLinks, ...outLinks]

  const pos = new Map<string, { x: number; y: number }>()
  const COLW = 360, ROWH = 76
  if (focusKey) pos.set(focusKey, { x: 0, y: 0 })
  const place = (keys: string[], x: number) =>
    keys.forEach((k, i) => pos.set(k, { x, y: (i - (keys.length - 1) / 2) * ROWH }))
  place(callers, -COLW)
  place(callees, COLW)
  return { pos, focusKey, visibleKeys, visibleLinks, byKey,
           rows: Math.max(callers.length, callees.length, 1) }
})

// 服务类型 → 本地打包的 Pinpoint 图标（远程 /img/icons 走代理会 502，故下载到 src/assets 本地用）
const ICON_FILES = import.meta.glob('../../../../../assets/pinpoint-icons/*.png',
  { eager: true, query: '?url', import: 'default' }) as Record<string, string>
const ICON_BY_TYPE: Record<string, string> = {}
for (const [p, url] of Object.entries(ICON_FILES)) {
  ICON_BY_TYPE[p.split('/').pop()!.replace('.png', '')] = url
}
// 变体归一化到有图标的基础类型
function iconType(st: string): string {
  const s = (st || 'UNKNOWN').toUpperCase()
  if (s.startsWith('REDIS')) return 'REDIS'
  if (s.startsWith('MYSQL')) return 'MYSQL'
  if (s.startsWith('MONGO')) return 'MONGODB'
  if (s.startsWith('POSTGRE')) return 'POSTGRESQL'
  return s
}

// 源图标仅 25px，直接放大会糊。用 canvas 把图标合成到矢量圆形「芯片」上：
// 圆+环高清绘制，图标居中近原生尺寸；环色编码状态（青=本次服务 / 红=有错误 / 灰=正常）。
type Ring = 'focus' | 'error' | 'normal'
const CHIP = 96                       // 合成画布边长（按 2x 显示，保证 retina 清晰）
const imgCache: Record<string, HTMLImageElement> = {}
const chipCache = ref<Record<string, string>>({})
const iconTick = ref(0)               // 图标异步加载完 → 自增触发重算

function loadIcon(type: string): HTMLImageElement {
  if (!imgCache[type]) {
    const img = new Image()
    img.onload = () => { iconTick.value++ }
    img.src = ICON_BY_TYPE[type] || ICON_BY_TYPE['UNKNOWN'] || ''
    imgCache[type] = img
  }
  return imgCache[type]
}
function chipKey(type: string, ring: Ring): string {
  return `${type}|${ring}|${props.isDark ? 'd' : 'l'}`
}
function buildChip(serviceType: string, ring: Ring): void {
  const type = iconType(serviceType)
  const key = chipKey(type, ring)
  if (chipCache.value[key]) return
  const img = loadIcon(type)
  if (!img.complete || !img.naturalWidth) return     // 未就绪，加载完 iconTick 触发重建
  const cv = document.createElement('canvas')
  cv.width = CHIP; cv.height = CHIP
  const ctx = cv.getContext('2d'); if (!ctx) return
  const r = CHIP / 2 - 6
  ctx.beginPath(); ctx.arc(CHIP / 2, CHIP / 2, r, 0, Math.PI * 2)
  ctx.fillStyle = props.isDark ? '#1e293b' : '#ffffff'; ctx.fill()
  ctx.lineWidth = ring === 'normal' ? 3 : 6
  ctx.strokeStyle = ring === 'focus' ? '#06b6d4' : ring === 'error' ? '#ef4444' : (props.isDark ? '#3b4658' : '#dbe1ea')
  ctx.stroke()
  const box = 56
  const scale = box / Math.max(img.naturalWidth, img.naturalHeight)
  const iw = img.naturalWidth * scale, ih = img.naturalHeight * scale
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(img, (CHIP - iw) / 2, (CHIP - ih) / 2, iw, ih)
  chipCache.value = { ...chipCache.value, [key]: cv.toDataURL('image/png') }
}
function ringOf(n: ServerMapNode): Ring {
  return n.key === layout.value.focusKey ? 'focus' : n.error_rate > 0 ? 'error' : 'normal'
}
// 预生成可见节点的芯片（不在 computed 里做副作用）
watchEffect(() => {
  void iconTick.value; void props.isDark   // deps
  for (const n of props.data.nodes) {
    if (layout.value.visibleKeys.has(n.key)) buildChip(n.service_type, ringOf(n))
  }
})

const maxCount = computed(() =>
  Math.max(1, ...props.data.nodes.map((n) => n.total_count)),
)
// 调用量 → 节点直径（log 压缩，14~52）
function sizeFor(count: number): number {
  const r = Math.log(count + 1) / Math.log(maxCount.value + 1)
  return Math.round(14 + 38 * r)
}
function edgeWidth(count: number): number {
  const r = Math.log(count + 1) / Math.log(maxCount.value + 1)
  return Math.max(1, Math.round(1 + 3 * r))
}

const chartNodes = computed(() =>
  props.data.nodes.filter((n) => layout.value.visibleKeys.has(n.key)).map((n) => {
    const p = layout.value.pos.get(n.key)
    const isFocus = n.key === layout.value.focusKey
    const chip = chipCache.value[chipKey(iconType(n.service_type), ringOf(n))]
    // 节点直径：芯片为视觉单位，按调用量在 38~52 间微调；焦点固定大些
    const size = isFocus ? 50 : Math.max(34, Math.min(46, sizeFor(n.total_count) + 8))
    const labelColor = isFocus ? '#06b6d4' : n.error_rate > 0 ? '#ef4444' : dim('rgba(0,0,0,0.72)', 'rgba(255,255,255,0.8)')
    return {
      name: n.key,                       // links 用 key 匹配（唯一）
      dispName: n.name || n.key,
      x: p?.x, y: p?.y,
      symbol: chip ? `image://${chip}` : 'circle',     // 芯片就绪前先占位圆
      symbolSize: size,
      itemStyle: chip ? {} : { color: isFocus ? '#06b6d4' : '#94a3b8' },
      label: { color: labelColor, fontWeight: isFocus ? 700 : 400, fontSize: isFocus ? 11.5 : 9.5 },
      stat: n,
    }
  }),
)
const chartLinks = computed(() => {
  const vis = layout.value.visibleLinks
  // 双向（来回）的边：同一对节点存在两个方向 → 各自弯到一侧，分成两条弧
  const dirSet = new Set(vis.map((l) => `${l.from}${l.to}`))
  const isBidir = (l: ServerMapLink) => dirSet.has(`${l.to}${l.from}`)
  return vis.map((l) => ({
    source: l.from,
    target: l.to,
    // 时间标签横排显示在线中间，带淡底保证可读（双向两条线各自的标签上下分开）
    label: {
      show: true, fontSize: 9, position: 'middle' as const,
      color: dim('rgba(0,0,0,0.7)', 'rgba(255,255,255,0.72)'),
      backgroundColor: dim('rgba(245,247,250,0.82)', 'rgba(18,26,38,0.8)'),
      padding: [1, 3] as [number, number], borderRadius: 3,
      formatter: () => `${l.total_count.toLocaleString()} (${l.avg_ms}ms)`,
    },
    lineStyle: {
      color: l.error_rate > 0 ? '#ef4444' : dim('rgba(0,0,0,0.3)', 'rgba(255,255,255,0.3)'),
      width: edgeWidth(l.total_count),
      opacity: l.error_rate > 0 ? 0.85 : 0.5,
      // 单向=直线；双向(来回)=两条近平行线，各弯到一侧分开
      curveness: isBidir(l) ? (l.from < l.to ? 0.2 : -0.2) : 0,
    },
    stat: l,
  }))
})

const option = computed(() => ({
  tooltip: {
    trigger: 'item' as const,
    backgroundColor: dim('#fff', '#1f2937'),
    borderColor: dim('rgba(0,0,0,0.1)', 'rgba(255,255,255,0.1)'),
    textStyle: { color: dim('#111', '#eee'), fontSize: 11 },
    formatter: (p: any) => {
      if (p.dataType === 'edge') {
        const l: ServerMapLink = p.data.stat
        return `${stripType(l.from)} → ${stripType(l.to)}<br/>`
          + `调用 ${l.total_count} · 错误 ${l.error_count}（${l.error_rate}%）<br/>`
          + `均延迟 ${l.avg_ms}ms · 最大 ${l.max_ms}ms · 慢 ${l.slow_count}`
      }
      const n: ServerMapNode = p.data.stat
      return `<b>${n.name}</b> <span style="opacity:.6">${n.service_type}</span><br/>`
        + `调用 ${n.total_count} · 错误 ${n.error_count}（${n.error_rate}%）· 慢 ${n.slow_count}`
    },
  },
  series: [{
    type: 'graph' as const,
    layout: 'none' as const,        // 用算好的 x/y：中心居中、上游左、下游右
    roam: true,                     // 滚轮/触控板缩放 + 拖动平移
    draggable: true,
    edgeSymbol: ['none', 'arrow'],
    edgeSymbolSize: 7,
    label: {
      show: true,
      position: 'bottom' as const,
      fontSize: 9,
      color: dim('rgba(0,0,0,0.7)', 'rgba(255,255,255,0.75)'),
      formatter: (p: any) => p.data.dispName ?? '',
    },
    emphasis: { focus: 'adjacency' as const, lineStyle: { width: 4 } },
    data: chartNodes.value,
    links: chartLinks.value,
  }],
}))

const serverMapUrl = computed(() =>
  props.data.pinpoint_base_url ? `${props.data.pinpoint_base_url}/serverMap` : '',
)
const hasLinks = computed(() => props.data.links.length > 0)
// 高度按可见列的行数（取调用方/被调中多的一边）自适应
// 紧凑画布；节点多时初始会挤，用滚轮/触控板放大查看
const chartHeight = computed(() => Math.min(560, Math.max(220, layout.value.rows * 50 + 50)))
</script>

<template>
  <div class="flex flex-col gap-2">
    <div class="flex items-center gap-1.5 px-1"
         :style="{ color: dim('rgba(0,0,0,0.65)', 'rgba(255,255,255,0.7)') }">
      <span class="w-0.5 h-3.5 rounded-full" style="background:#06b6d4" />
      <span class="text-[12px] font-medium">服务拓扑 · Pinpoint（{{ data.nodes.length }} 节点 / {{ data.links.length }} 调用）</span>
      <span v-if="data.fallback_recent" class="text-[10px] px-1.5 py-0.5 rounded-md"
            :style="{ color: '#b45309', background: dim('#fef3c7', 'rgba(245,158,11,0.15)') }"
            title="run 时段 Pinpoint 无该服务拓扑，展示近 30 分钟参考拓扑">近期</span>
      <a v-if="serverMapUrl" :href="serverMapUrl" target="_blank" rel="noopener"
         class="ml-auto inline-flex items-center gap-0.5 text-[11px] text-blue-500 hover:underline">
        在 Pinpoint 打开 <ExternalLink :size="11" />
      </a>
    </div>

    <!-- 跳过的服务提示 -->
    <p v-if="data.skipped?.length" class="text-[10.5px] px-1"
       :style="{ color: dim('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">
      未含拓扑：{{ data.skipped.map(s => s.service).join('、') }}（不是 Pinpoint 应用，可在 admin 配 pinpoint_app）
    </p>

    <!-- 无上下游调用：收成一行提示，不占大片空白 -->
    <p v-if="!hasLinks" class="text-[11px] py-3 text-center rounded-lg"
       :style="{ color: dim('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.45)'), background: dim('rgba(0,0,0,0.02)', 'rgba(255,255,255,0.02)') }">
      该服务在此时段无上下游调用关系（Pinpoint 未采到链路）
    </p>

    <!-- 拓扑图 + 依赖表（有调用关系才显示）-->
    <template v-else>
    <div class="rounded-lg" :style="{ background: dim('rgba(0,0,0,0.02)', 'rgba(255,255,255,0.02)') }">
      <VChart :option="option" autoresize :style="{ width:'100%', height: chartHeight + 'px' }" />
    </div>
    <p class="text-[10px] px-1" :style="{ color: dim('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">
      中心=本次服务（青环）· 左=主要调用方 / 右=主要被调（各 top {{ TOP_N }}）· 图标=服务类型 · 红环=有错误 · 滚轮/触控板缩放、拖动平移 · 点节点/连线看明细 · 完整拓扑点「在 Pinpoint 打开」
    </p>
    </template>
  </div>
</template>
