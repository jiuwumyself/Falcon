<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, TitleComponent, MarkPointComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { TGKind } from '@/types/task'

use([
  LineChart, GridComponent, TooltipComponent, TitleComponent, MarkPointComponent,
  CanvasRenderer,
])

const props = defineProps<{
  kind: TGKind
  params: Record<string, number | string>
  scenarioColor: string
  isDark: boolean
}>()

interface Point { t: number; y: number }

function toNum(v: unknown, fb = 0): number {
  const n = typeof v === 'string' ? Number(v) : (v as number)
  return Number.isFinite(n) ? n : fb
}

// 产出 (time_seconds, active_units) 折线点
const rawPoints = computed<Point[]>(() => {
  const p = props.params
  if (props.kind === 'ThreadGroup') {
    const users = toNum(p.users, 10)
    const ramp = toNum(p.ramp_up, 0)
    const dur = Math.max(ramp + 1, toNum(p.duration, 60))
    return [
      { t: 0, y: 0 },
      { t: ramp, y: users },
      { t: dur, y: users },
      { t: dur, y: 0 },
    ]
  }
  if (props.kind === 'SteppingThreadGroup') {
    const initial = toNum(p.initial_threads, 0)
    const stepU = toNum(p.step_users, 10)
    const stepD = Math.max(1, toNum(p.step_delay, 30))
    const stepC = Math.max(0, toNum(p.step_count, 10))
    const hold = toNum(p.hold, 60)
    const shutdown = Math.max(0, toNum(p.shutdown, 1))

    const pts: Point[] = [{ t: 0, y: 0 }]
    if (initial > 0) pts.push({ t: 0, y: initial })
    let curT = 0
    let curY = initial
    for (let i = 1; i <= stepC; i++) {
      curT += stepD
      pts.push({ t: curT, y: curY })
      curY += stepU
      pts.push({ t: curT, y: curY })
    }
    curT += hold
    pts.push({ t: curT, y: curY })
    curT += shutdown
    pts.push({ t: curT, y: 0 })
    return pts
  }
  if (props.kind === 'ConcurrencyThreadGroup' || props.kind === 'ArrivalsThreadGroup') {
    const target = props.kind === 'ConcurrencyThreadGroup'
      ? toNum(p.target_concurrency, 100)
      : toNum(p.target_rps, 500)
    const ramp = Math.max(0, toNum(p.ramp_up, 10))
    const steps = Math.max(0, toNum(p.steps, 5))
    const hold = toNum(p.hold, 60)
    const unit = (p.unit as string) === 'M' ? 60 : 1
    const holdSec = hold * unit

    const pts: Point[] = [{ t: 0, y: 0 }]
    if (steps > 0 && ramp > 0) {
      const dt = ramp / steps
      const dy = target / steps
      for (let i = 1; i <= steps; i++) {
        pts.push({ t: i * dt, y: (i - 1) * dy })
        pts.push({ t: i * dt, y: i * dy })
      }
    } else {
      pts.push({ t: ramp, y: target })
    }
    pts.push({ t: ramp + holdSec, y: target })
    pts.push({ t: ramp + holdSec, y: 0 })
    return pts
  }
  if (props.kind === 'UltimateThreadGroup') {
    // 兼容老格式（flat dict）和新格式（rows 数组）
    type PeakRow = { users: number; initial_delay: number; ramp_up: number; hold: number; shutdown: number }
    let rows: PeakRow[]
    if (Array.isArray(p.rows) && p.rows.length > 0) {
      rows = (p.rows as any[]).map((r) => ({
        users: toNum(r.users, 500),
        initial_delay: Math.max(0, toNum(r.initial_delay, 0)),
        ramp_up: Math.max(0, toNum(r.ramp_up, 5)),
        hold: Math.max(0, toNum(r.hold, 60)),
        shutdown: Math.max(0, toNum(r.shutdown, 5)),
      }))
    } else {
      rows = [{
        users: toNum(p.users, 500),
        initial_delay: Math.max(0, toNum(p.initial_delay, 0)),
        ramp_up: Math.max(0, toNum(p.ramp_up, 5)),
        hold: Math.max(0, toNum(p.hold, 60)),
        shutdown: Math.max(0, toNum(p.shutdown, 5)),
      }]
    }

    // 每行在时刻 t 的活跃用户数（线性 ramp up/down）
    function rowAt(r: PeakRow, t: number): number {
      const t0 = r.initial_delay
      const t1 = t0 + r.ramp_up
      const t2 = t1 + r.hold
      const t3 = t2 + r.shutdown
      if (t <= t0) return 0
      if (t <= t1) return r.users * (t - t0) / Math.max(1, r.ramp_up)
      if (t <= t2) return r.users
      if (t <= t3) return r.users * (t3 - t) / Math.max(1, r.shutdown)
      return 0
    }

    // 收集所有关键时刻点
    const times = new Set<number>([0])
    for (const r of rows) {
      times.add(r.initial_delay)
      times.add(r.initial_delay + r.ramp_up)
      times.add(r.initial_delay + r.ramp_up + r.hold)
      times.add(r.initial_delay + r.ramp_up + r.hold + r.shutdown)
    }
    return Array.from(times).sort((a, b) => a - b).map((t) => ({
      t,
      y: rows.reduce((sum, r) => sum + rowAt(r, t), 0),
    }))
  }
  return [{ t: 0, y: 0 }]
})

const yAxisName = computed(() => (
  props.kind === 'ArrivalsThreadGroup' ? 'RPS' : '活跃用户数'
))

function fmtTime(s: number): string {
  if (s < 60) return `${Math.round(s)}s`
  if (s < 3600) return `${Math.round(s / 60)}m ${Math.round(s % 60)}s`
  const h = Math.floor(s / 3600)
  const m = Math.round((s - h * 3600) / 60)
  return `${h}h ${m}m`
}

const chartOption = computed(() => {
  const pts = rawPoints.value
  const peakY = pts.reduce((m, p) => Math.max(m, p.y), 0)
  const totalT = pts.reduce((m, p) => Math.max(m, p.t), 1)

  const axisColor = props.isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.3)'
  const labelColor = props.isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)'
  const gridColor = props.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'

  // Build a subtle gradient fill
  return {
    grid: { left: 55, right: 24, top: 30, bottom: 40 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: props.isDark ? 'rgba(20,20,30,0.95)' : 'rgba(255,255,255,0.98)',
      borderColor: props.scenarioColor,
      borderWidth: 1,
      textStyle: { color: props.isDark ? '#e8e8ed' : '#1a1a2e', fontSize: 12 },
      formatter: (params: any) => {
        const p = params[0]
        return `${fmtTime(p.value[0])}<br/><strong style="color:${props.scenarioColor}">${Math.round(p.value[1])}</strong> ${yAxisName.value}`
      },
    },
    xAxis: {
      type: 'value',
      name: '时间',
      nameLocation: 'middle',
      nameGap: 24,
      min: 0,
      max: Math.ceil(totalT),
      axisLabel: {
        formatter: (v: number) => fmtTime(v),
        color: labelColor,
        fontSize: 10,
      },
      axisLine: { lineStyle: { color: axisColor } },
      splitLine: { lineStyle: { color: gridColor, type: 'dashed' } },
      nameTextStyle: { color: labelColor, fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      name: yAxisName.value,
      nameLocation: 'middle',
      nameGap: 36,
      min: 0,
      max: Math.max(10, Math.ceil(peakY * 1.1)),
      axisLabel: { color: labelColor, fontSize: 10 },
      axisLine: { lineStyle: { color: axisColor } },
      splitLine: { lineStyle: { color: gridColor, type: 'dashed' } },
      nameTextStyle: { color: labelColor, fontSize: 10 },
    },
    series: [
      {
        name: yAxisName.value,
        type: 'line',
        data: pts.map((p) => [p.t, p.y]),
        showSymbol: false,
        lineStyle: { color: props.scenarioColor, width: 2.5 },
        itemStyle: { color: props.scenarioColor },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: `${props.scenarioColor}55` },
              { offset: 1, color: `${props.scenarioColor}00` },
            ],
          },
        },
        smooth: 0,  // keep the piecewise-linear look; these are exact plans
        markPoint: {
          data: [{ type: 'max', name: '峰值' }],
          symbol: 'circle',
          symbolSize: 8,
          itemStyle: { color: props.scenarioColor },
          label: {
            formatter: (p: any) => `${Math.round(p.value)}`,
            fontSize: 10,
            color: '#fff',
          },
        },
      },
    ],
  }
})
</script>

<template>
  <div
    class="rounded-xl p-3"
    :style="{
      background: isDark ? 'rgba(0,0,0,0.2)' : 'rgba(255,255,255,0.4)',
      border: `1px solid ${isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'}`,
      height: '320px',
    }"
  >
    <VChart
      :option="chartOption"
      :autoresize="true"
      style="height: 100%; width: 100%"
    />
  </div>
</template>
