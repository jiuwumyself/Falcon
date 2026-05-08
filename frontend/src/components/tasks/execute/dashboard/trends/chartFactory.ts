/**
 * 统一 echarts 配置工厂 —— grid / xAxis / yAxis / tooltip / legend 默认风格。
 * 每张图传入主题色即可，避免每个组件都重复一份 option 模板。
 *
 * 时间游标联动：调用方在挂载后 `connect('falcon-trends')` 把所有图绑成一组，
 * hover 任何一张，其它图都会高亮同一时间点。
 */

import type { SeriesPoint } from '@/types/task'

export interface ChartTheme {
  isDark: boolean
}

export interface SeriesSpec {
  name: string
  data: SeriesPoint[]
  color: string
  lineWidth?: number
  /** 数值格式化器（tooltip 用）。默认 (.toFixed(2) + unit) */
  formatter?: (val: number) => string
  /** 是否堆叠（NetworkChart 用） */
  stack?: string
  /** 是否填充区域（all 加粗系列默认填，其它默认不填） */
  area?: boolean
}

export const CONNECT_GROUP = 'falcon-trends'

export function axisColor(isDark: boolean): string {
  return isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.3)'
}

export function labelColor(isDark: boolean): string {
  return isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)'
}

export function gridLineColor(isDark: boolean): string {
  return isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'
}

export function tooltipBg(isDark: boolean) {
  return {
    backgroundColor: isDark ? 'rgba(20,20,30,0.94)' : 'rgba(255,255,255,0.97)',
    borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
    textStyle: { color: isDark ? '#e4e4e7' : '#1a1a2e', fontSize: 11 },
  }
}

export function buildSeriesOption(
  series: SeriesSpec[],
  isDark: boolean,
  unit: string,
  opts: {
    showLegend?: boolean
    gridBottom?: number
    /** small multiples 紧贴布局用：上面的图隐藏 x 轴标签让最底下一张承担 */
    hideXAxisLabel?: boolean
  } = {},
) {
  const { showLegend = true, hideXAxisLabel = false } = opts
  const gridBottom = opts.gridBottom ?? (hideXAxisLabel ? 8 : 28)

  return {
    grid: {
      left: 60,
      right: 16,
      top: showLegend ? 36 : 16,
      bottom: gridBottom,
    },
    legend: showLegend
      ? {
          show: true,
          top: 0,
          left: 'center',
          textStyle: { color: labelColor(isDark), fontSize: 11 },
          icon: 'roundRect',
          itemWidth: 12,
          itemHeight: 4,
          itemGap: 12,
          data: series.map((s) => s.name),
        }
      : { show: false },
    tooltip: {
      trigger: 'axis' as const,
      ...tooltipBg(isDark),
      axisPointer: {
        type: 'line' as const,
        lineStyle: { color: isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.2)' },
      },
      formatter: (params: any) => {
        const arr = Array.isArray(params) ? params : [params]
        if (!arr.length) return ''
        const ts = new Date(arr[0].value[0])
        const tsStr = ts.toLocaleTimeString('zh-CN', { hour12: false })
        const lines = arr
          .filter((p: any) => p.value && p.value[1] != null)
          .sort((a: any, b: any) => b.value[1] - a.value[1])
          .map((p: any) => {
            const spec = series.find((s) => s.name === p.seriesName)
            const v = spec?.formatter
              ? spec.formatter(p.value[1])
              : `${p.value[1].toFixed(2)} ${unit}`
            return `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color};margin-right:6px"></span>${p.seriesName}: <b>${v}</b>`
          })
        return `<div style="font-size:10.5px;color:${labelColor(isDark)};margin-bottom:4px">${tsStr}</div>${lines.join('<br/>')}`
      },
    },
    xAxis: {
      type: 'time' as const,
      axisLine: { lineStyle: { color: axisColor(isDark) } },
      axisLabel: hideXAxisLabel
        ? { show: false }
        : { color: labelColor(isDark), fontSize: 10 },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value' as const,
      axisLine: { show: false },
      axisLabel: { color: labelColor(isDark), fontSize: 10 },
      splitLine: { lineStyle: { color: gridLineColor(isDark) } },
    },
    series: series.map((s) => ({
      type: 'line' as const,
      name: s.name,
      data: s.data,
      smooth: true,
      symbol: 'none' as const,
      stack: s.stack,
      lineStyle: { color: s.color, width: s.lineWidth ?? 1.2 },
      itemStyle: { color: s.color },
      areaStyle: s.area
        ? {
            color: {
              type: 'linear' as const,
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: hexToAlpha(s.color, 0.32) },
                { offset: 1, color: hexToAlpha(s.color, 0) },
              ],
            },
          }
        : undefined,
    })),
  }
}

function hexToAlpha(hex: string, alpha: number): string {
  if (hex.length !== 7 || hex[0] !== '#') return hex
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r},${g},${b},${alpha})`
}

/** 算 series 的 mean / max / min（右侧统计表用），忽略 null */
export function statsOf(data: SeriesPoint[]): { mean: number; max: number; min: number } {
  if (!data.length) return { mean: 0, max: 0, min: 0 }
  let sum = 0
  let max = -Infinity
  let min = Infinity
  let n = 0
  for (const p of data) {
    const v = p[1]
    if (v == null || Number.isNaN(v)) continue
    sum += v
    if (v > max) max = v
    if (v < min) min = v
    n++
  }
  if (!n) return { mean: 0, max: 0, min: 0 }
  return { mean: sum / n, max, min }
}

/** 把字节速率（每秒）格式化成 KiB/s · MiB/s · GiB/s */
export function fmtBytesRate(bps: number): string {
  if (bps < 1024) return `${bps.toFixed(0)} B/s`
  if (bps < 1024 * 1024) return `${(bps / 1024).toFixed(1)} KiB/s`
  if (bps < 1024 * 1024 * 1024) return `${(bps / 1024 / 1024).toFixed(1)} MiB/s`
  return `${(bps / 1024 / 1024 / 1024).toFixed(2)} GiB/s`
}

/** 把累计字节格式化成 KiB · MiB · GiB（KpiBar 用） */
export function fmtBytesTotal(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MiB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GiB`
}

/** 千分位整数 */
export function fmtInt(n: number): string {
  if (n == null || Number.isNaN(n)) return '—'
  return Math.round(n).toLocaleString()
}
