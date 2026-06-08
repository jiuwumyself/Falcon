// 服务诊断 Pod 时序面板的纯函数工厂（per-pod 多线 + 统计），复用 trends/chartFactory 配色。
import type { PrometheusMetricSeries } from '@/types/task'
import { axisColor, gridLineColor, labelColor, tooltipBg } from '../trends/chartFactory'

// Grafana 风格多彩 pod 线
export const POD_COLORS = [
  '#5794f2', '#1d9e75', '#ba7517', '#c4162a', '#806eb7',
  '#82b5d8', '#e5a216', '#6ccf8e', '#ff780a', '#0a50a1',
]

export interface NamedSeries { name: string; data: [number, number][]; color: string }

export function computeStats(data: [number, number][]): { mean: number; max: number } {
  if (!data.length) return { mean: 0, max: 0 }
  const v = data.map((d) => d[1])
  return { mean: v.reduce((a, b) => a + b, 0) / v.length, max: Math.max(...v) }
}

// per-pod 数据 → 每个 pod 一条线（短名：去 deployment hash 前缀后的尾段）
export function podsToSeries(
  pods: Record<string, { ts: number; value: number }[]> | undefined,
): NamedSeries[] {
  if (!pods) return []
  return Object.keys(pods).sort().map((name, i) => ({
    name,
    data: pods[name].map((d) => [d.ts * 1000, d.value] as [number, number]),
    color: POD_COLORS[i % POD_COLORS.length],
  }))
}

export function seriesFrom(
  s: PrometheusMetricSeries | undefined,
  name: string,
  color: string,
): NamedSeries | null {
  if (!s?.data?.length) return null
  return { name, data: s.data.map((d) => [d.ts * 1000, d.value] as [number, number]), color }
}

export function makeLineOption(series: NamedSeries[], unit: string, isDark: boolean) {
  return {
    grid: { top: 10, left: 46, right: 12, bottom: 22 },
    tooltip: {
      trigger: 'axis' as const,
      ...tooltipBg(isDark),
      valueFormatter: (v: any) => `${Number(v).toFixed(1)}${unit}`,
    },
    legend: { show: false },
    xAxis: {
      type: 'time' as const,
      axisLine: { lineStyle: { color: axisColor(isDark) } },
      axisLabel: { fontSize: 9, color: labelColor(isDark) },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value' as const,
      axisLine: { show: false },
      axisLabel: { fontSize: 9, color: labelColor(isDark) },
      splitLine: { lineStyle: { color: gridLineColor(isDark) } },
    },
    series: series.map((s) => ({
      type: 'line' as const,
      name: s.name,
      data: s.data,
      smooth: true,
      symbol: 'none',
      lineStyle: { width: 1.4, color: s.color },
    })),
  }
}
