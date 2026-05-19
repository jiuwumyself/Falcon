<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { ScatterChart, LineChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, TitleComponent, VisualMapComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { SeriesPoint } from '@/types/task'
import HoverTip from './HoverTip.vue'

use([ScatterChart, LineChart, GridComponent, TooltipComponent, TitleComponent, VisualMapComponent, CanvasRenderer])

// 并发-RPS 关系散点图：横轴并发 VU / 纵轴 RPS / 每个时间点一个散点
// 用时间维度做 visualMap 颜色梯度（早期淡 → 后期深），看出压力推进路径
// 一眼看出：线性增长 / 平台期 / 性能拐点 / 系统崩盘
//
// showTrendLine（soak 场景开启）：恒定并发模式下额外叠一条 RPS vs time 线性回归
// 直线 + 显示斜率（req/s/min）。soak 漂移诊断金标准：CV% 看抖动幅度，斜率看
// "缓慢漂移"——CV% OK 但斜率显著 ≠ 0 = 长跑衰减（内存泄漏 / 连接池 leak）。
const props = defineProps<{
  rps: SeriesPoint[]
  vu: SeriesPoint[]
  isDark: boolean
  showTrendLine?: boolean
}>()

interface ScatterPoint { vu: number; rps: number; ts: number }

// 按 timestamp 对齐两条序列，O(N+M) 双指针。
// rps 来自 InfluxDB 1s 桶（地板时钟），vu 可能来自 dense plannedCurve（从
// run.started_at 起算每 1s），两者时间戳通常差 < 1s 不严格等。exact get 会全 miss
// 让散点图空，所以在 ±1.5s 窗口内做最近匹配。
const points = computed<ScatterPoint[]>(() => {
  if (!props.rps.length || !props.vu.length) return []
  const NEAR_MS = 1500
  const vuArr = props.vu
  const out: ScatterPoint[] = []
  let j = 0
  for (const [t, r] of props.rps) {
    while (j + 1 < vuArr.length && Math.abs(vuArr[j + 1][0] - t) <= Math.abs(vuArr[j][0] - t)) {
      j++
    }
    const [vt, vu] = vuArr[j]
    if (vu <= 0 || Math.abs(vt - t) > NEAR_MS) continue
    out.push({ vu, rps: r, ts: t })
  }
  return out
})

// 散点图实际渲染用的稳态点（剔除 ramp-up 阶段的 VU<80% 目标 的样本）
// 否则恒定 VU 场景会出现"X=2 那个孤零零的 ramp 期点"
const steadyPoints = computed(() => steadyStatePoints(points.value))

const tsRange = computed(() => {
  const pts = steadyPoints.value
  if (!pts.length) return [0, 0]
  return [pts[0].ts, pts[pts.length - 1].ts]
})

const option = computed(() => {
  const pts = steadyPoints.value
  // 恒定并发场景（稳定性 / soak）：X 轴改时间，让点散开成"RPS 时序气泡图"
  // 否则所有点挤在 X=VU 一条竖线，浪费 80% 水平空间
  const flat = summary.value?.isFlatVu ?? false
  // 压力梯度模式：[VU, RPS, ts]；恒定并发模式：[ts, RPS, ts]
  const data = pts.map((p) => flat ? [p.ts, p.rps, p.ts] : [p.vu, p.rps, p.ts])
  const [tsMin, tsMax] = tsRange.value
  const axisColor = props.isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)'
  const gridLine = props.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'
  return {
    grid: { left: 50, right: 18, top: 18, bottom: 38 },
    tooltip: {
      trigger: 'item' as const,
      formatter: (p: any) => {
        const [, rps, ts] = p.value
        const date = new Date(ts)
        const hh = String(date.getHours()).padStart(2, '0')
        const mm = String(date.getMinutes()).padStart(2, '0')
        const ss = String(date.getSeconds()).padStart(2, '0')
        // 恒定并发模式不重复 VU；压力梯度模式显示 VU
        if (flat) {
          return `${hh}:${mm}:${ss}<br/>RPS ${rps.toFixed(1)} req/s`
        }
        const vu = p.value[0]
        return `${hh}:${mm}:${ss}<br/>并发 ${vu} VU<br/>吞吐 ${rps.toFixed(1)} req/s`
      },
      backgroundColor: props.isDark ? 'rgba(20,20,22,0.92)' : 'rgba(255,255,255,0.95)',
      borderColor: props.isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)',
      textStyle: { color: props.isDark ? '#fff' : '#000', fontSize: 11 },
    },
    visualMap: {
      show: false,
      min: tsMin,
      max: tsMax,
      dimension: 2,    // 用第三维（ts）做颜色映射
      inRange: {
        color: props.isDark
          ? ['rgba(168,85,247,0.25)', 'rgba(168,85,247,0.95)']
          : ['rgba(168,85,247,0.20)', 'rgba(124,58,237,0.95)'],
      },
    },
    xAxis: flat
      ? {
          type: 'time' as const,
          name: '时间',
          nameLocation: 'middle' as const,
          nameGap: 24,
          nameTextStyle: { color: axisColor, fontSize: 10 },
          axisLine: { lineStyle: { color: axisColor } },
          axisLabel: { color: axisColor, fontSize: 10 },
          splitLine: { show: false },
        }
      : {
          type: 'value' as const,
          name: '并发 VU',
          nameLocation: 'middle' as const,
          nameGap: 24,
          nameTextStyle: { color: axisColor, fontSize: 10 },
          axisLine: { lineStyle: { color: axisColor } },
          axisLabel: { color: axisColor, fontSize: 10 },
          splitLine: { lineStyle: { color: gridLine } },
        },
    yAxis: {
      type: 'value' as const,
      name: 'RPS',
      nameLocation: 'middle' as const,
      nameGap: 38,
      nameTextStyle: { color: axisColor, fontSize: 10 },
      axisLine: { lineStyle: { color: axisColor } },
      axisLabel: { color: axisColor, fontSize: 10 },
      splitLine: { lineStyle: { color: gridLine } },
    },
    series: (() => {
      const list: any[] = [
        {
          type: 'scatter' as const,
          symbolSize: 6,
          data,
          emphasis: { focus: 'self' as const },
        },
      ]
      // soak 模式：叠一条线性回归直线（仅 flat + showTrendLine + trend 算得出）
      if (flat && props.showTrendLine && summary.value?.trend) {
        const { slope, intercept, t0, t1 } = summary.value.trend
        // slope 在 summary 里已是 req/s/min；恢复成 req/s/sec 算端点
        const slopePerSec = slope / 60
        const y0 = intercept
        const y1 = intercept + slopePerSec * ((t1 - t0) / 1000)
        list.push({
          type: 'line' as const,
          showSymbol: false,
          data: [[t0, y0, t0], [t1, y1, t1]],
          lineStyle: { color: '#f59e0b', width: 1.6, type: 'dashed' },
          tooltip: { show: false },
          z: 1,
        })
      }
      return list
    })(),
  }
})

// 排除前几秒 ramp-up（VU 从 0 爬到目标）的样本，避免它们扰动"恒定并发"判定
function steadyStatePoints(pts: ScatterPoint[]): ScatterPoint[] {
  if (pts.length <= 5) return pts
  let maxVu = 0
  for (const p of pts) if (p.vu > maxVu) maxVu = p.vu
  // 取已经爬到 80% 目标 VU 之后的点
  const threshold = maxVu * 0.8
  const steady = pts.filter((p) => p.vu >= threshold)
  return steady.length >= 5 ? steady : pts
}

const summary = computed(() => {
  const all = points.value
  if (!all.length) return null
  const pts = steadyStatePoints(all)

  // VU 抖动：max-min 跟 mean 比，判定"恒定并发"场景（稳定性测试）
  let vuMin = Infinity
  let vuMax = 0
  let vuSum = 0
  for (const p of pts) {
    if (p.vu < vuMin) vuMin = p.vu
    if (p.vu > vuMax) vuMax = p.vu
    vuSum += p.vu
  }
  const vuMean = vuSum / pts.length
  // 稳定态 VU 变化 < 10% → 视作"恒定并发"
  const isFlatVu = vuMean > 0 && (vuMax - vuMin) / vuMean < 0.1

  // RPS 统计
  let rpsSum = 0
  let rpsMax = 0
  let peakRpsAtVu = 0
  let maxVu = 0
  let rpsAtMaxVu = 0
  const rpsArr: number[] = []
  for (const p of pts) {
    rpsSum += p.rps
    rpsArr.push(p.rps)
    if (p.rps > rpsMax) {
      rpsMax = p.rps
      peakRpsAtVu = p.vu
    }
    if (p.vu > maxVu) {
      maxVu = p.vu
      rpsAtMaxVu = p.rps
    }
  }
  const rpsMean = rpsSum / pts.length
  // 标准差
  let varSum = 0
  for (const r of rpsArr) varSum += (r - rpsMean) ** 2
  const rpsStd = Math.sqrt(varSum / pts.length)
  // 变异系数（CV = std/mean），衡量抖动幅度
  const rpsCv = rpsMean > 0 ? rpsStd / rpsMean : 0
  // P95
  const sortedRps = [...rpsArr].sort((a, b) => a - b)
  const rpsP95 = sortedRps[Math.floor(sortedRps.length * 0.95)] || rpsMax

  // 降级判定（仅压力梯度场景才有意义；恒定并发时 peakRpsAtVu === maxVu，自然 false）
  const degraded = peakRpsAtVu < maxVu && rpsAtMaxVu < rpsMax * 0.9

  // 仅在 isFlatVu 且开启 showTrendLine 时算线性回归（soak 漂移诊断）
  // RPS vs time 最小二乘拟合：slope（req/s/min）+ 起止两点坐标
  let trend: { slope: number; intercept: number; t0: number; t1: number } | null = null
  if (isFlatVu) {
    // 中心化 t 防 Number 溢出 / 数值不稳
    const t0 = pts[0].ts
    let sxT = 0, sxY = 0, sxx = 0, sxy = 0
    const n = pts.length
    for (const p of pts) {
      const x = (p.ts - t0) / 1000  // 秒
      sxT += x
      sxY += p.rps
      sxx += x * x
      sxy += x * p.rps
    }
    const meanX = sxT / n
    const meanY = sxY / n
    const denom = sxx - n * meanX * meanX
    if (denom > 1e-9) {
      const slopePerSec = (sxy - n * meanX * meanY) / denom
      const intercept = meanY - slopePerSec * meanX
      trend = {
        slope: slopePerSec * 60,  // 转 req/s/min（用户友好）
        intercept,
        t0,
        t1: pts[pts.length - 1].ts,
      }
    }
  }

  return {
    isFlatVu,
    vuMean,
    peakRps: rpsMax,
    peakRpsAtVu,
    maxVu,
    rpsAtMaxVu,
    degraded,
    rpsMean,
    rpsStd,
    rpsCv,
    rpsP95,
    trend,
  }
})

// tooltip 文案：分情况返字符串。Vue template 编译器对多行三元 + 反引号在 attribute
// 里的解析有 bug，挪到 computed 里安全。
const titleTooltip = computed(() => {
  if (summary.value?.isFlatVu) {
    if (props.showTrendLine) {
      return [
        '核心问题（稳定性 / soak）：长时间跑 RT/RPS 是否缓慢漂移？',
        '',
        '判读条件：',
        '· CV ≤ 5% → 干净基线',
        '· CV 5%-10% → 一般可接受',
        '· CV > 10% → 抖动严重',
        '· 回归斜率 |slope| < 0.05 → 平稳无漂移',
        '· 0.05 ≤ |slope| < 0.2 → 轻微漂移，关注',
        '· |slope| ≥ 0.2 → 显著漂移，疑似内存泄漏 / 连接池 leak',
      ].join('\n')
    }
    return [
      '核心问题（基准）：在轻负载下系统的"裸"稳定度如何？将来对比的参照系',
      '',
      '判读条件：',
      '· CV ≤ 5% → 干净基线，可作回归测试参考点',
      '· CV 5%-10% → 一般可接受',
      '· CV > 10% → 有问题，可能 GC 撞 / 后端 worker 不稳',
      '· P95 / 均值 > 1.3 → 长尾严重，不适合做基线',
    ].join('\n')
  }
  return [
    '核心问题（负载 / 压力）：阶梯加 VU 到哪 RPS 不再增长 = 系统拐点',
    '',
    '判读条件：',
    '· 散点直线斜向上 → 线性可扩展段',
    '· 散点平贴一条水平 → 平台期，到瓶颈',
    '· 散点下行 → 崩溃前兆（加 VU 反而 RPS 降）',
    '· ⚠ 标记 = 加 VU 后 RPS 反而比峰值低 10%+ → 已退化',
    '· 颜色越深越靠后，方便看推进路径',
  ].join('\n')
})
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="flex items-center justify-between px-1 mb-1">
      <HoverTip :tip="titleTooltip" :is-dark="isDark">
        <span class="text-[11.5px]"
              :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }">
          {{ summary?.isFlatVu ? 'RPS 抖动（并发恒定）' : '并发-吞吐关系' }}
        </span>
      </HoverTip>
      <div
        v-if="summary"
        class="text-[10.5px] tabular-nums"
        :style="{
          color: summary.degraded
            ? '#ef4444'
            : (isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)'),
        }"
      >
        <template v-if="summary.isFlatVu">
          {{ Math.round(summary.vuMean) }} VU · 均值 {{ summary.rpsMean.toFixed(0) }} ·
          抖动 ±{{ summary.rpsStd.toFixed(0) }} ({{ (summary.rpsCv * 100).toFixed(1) }}%) ·
          P95 {{ summary.rpsP95.toFixed(0) }}
          <span
            v-if="props.showTrendLine && summary.trend"
            :style="{
              color: Math.abs(summary.trend.slope) < 0.05
                ? '#10b981'
                : (Math.abs(summary.trend.slope) < 0.2 ? '#f59e0b' : '#ef4444'),
            }"
            :title="'线性回归斜率：每分钟 RPS 变化量。\n|slope| <0.05 平稳；0.05-0.20 轻微漂移；>0.20 显著漂移（疑似内存/连接池泄漏）'"
          >· 斜率 {{ summary.trend.slope >= 0 ? '+' : '' }}{{ summary.trend.slope.toFixed(2) }} req/s/min</span>
        </template>
        <template v-else-if="summary.degraded">
          ⚠ 加 VU 不涨吞吐（峰值 {{ summary.peakRps.toFixed(0) }} @ {{ summary.peakRpsAtVu }} VU）
        </template>
        <template v-else>
          峰值 {{ summary.peakRps.toFixed(0) }} req/s @ {{ summary.peakRpsAtVu }} VU
        </template>
      </div>
    </div>
    <div class="flex-1 min-h-0">
      <VChart
        v-if="points.length"
        :option="option"
        autoresize
        style="width: 100%; height: 100%"
      />
      <div
        v-else
        class="h-full flex items-center justify-center text-[11px]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)' }"
      >
        暂无数据
      </div>
    </div>
  </div>
</template>
