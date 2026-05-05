import type { ThreadGroupConfig } from '@/types/task'

// 把 ConcurrencyTG / ArrivalsTG 的 unit (S/M) 折算到秒。
function toSeconds(value: number, unit: 'S' | 'M' | string | undefined): number {
  if (unit === 'M') return Math.round(value * 60)
  return Math.round(value)
}

/**
 * 把所有启用 TG 的"计划线程上限"求和。
 * Arrivals 是 RPS 驱动 → 没有固定线程数，按 0 计。
 */
export function plannedThreads(cfgs: ThreadGroupConfig[] | undefined): number {
  if (!cfgs?.length) return 0
  let total = 0
  for (const cfg of cfgs) {
    const p = cfg.params || {}
    switch (cfg.kind) {
      case 'ThreadGroup':
        total += Number(p.users) || 0
        break
      case 'SteppingThreadGroup':
        total += (Number(p.initial_threads) || 0) +
          (Number(p.step_users) || 0) * (Number(p.step_count) || 0)
        break
      case 'ConcurrencyThreadGroup':
        total += Number(p.target_concurrency) || 0
        break
      case 'UltimateThreadGroup': {
        const rows = Array.isArray(p.rows) ? p.rows : []
        for (const r of rows) total += Number(r?.users) || 0
        break
      }
      case 'ArrivalsThreadGroup':
        // 不计入线程数（按 RPS 驱动）
        break
    }
  }
  return total
}

/**
 * 单个 TG 的等效总秒数（ramp + hold + 退出）。多 TG 取最大（并行）。
 */
function tgDurationSec(cfg: ThreadGroupConfig): number {
  const p = cfg.params || {}
  switch (cfg.kind) {
    case 'ThreadGroup':
      return (Number(p.ramp_up) || 0) + (Number(p.duration) || 0)
    case 'SteppingThreadGroup':
      return (Number(p.step_delay) || 0) * (Number(p.step_count) || 0) +
        (Number(p.hold) || 0) + (Number(p.shutdown) || 0)
    case 'ConcurrencyThreadGroup': {
      const unit = String(p.unit || 'S')
      return toSeconds(Number(p.ramp_up) || 0, unit) + toSeconds(Number(p.hold) || 0, unit)
    }
    case 'UltimateThreadGroup': {
      const rows = Array.isArray(p.rows) ? p.rows : []
      let max = 0
      for (const r of rows) {
        const sec = (Number(r?.initial_delay) || 0) +
          (Number(r?.ramp_up) || 0) +
          (Number(r?.hold) || 0) +
          (Number(r?.shutdown) || 0)
        if (sec > max) max = sec
      }
      return max
    }
    case 'ArrivalsThreadGroup': {
      const unit = String(p.unit || 'M')
      return toSeconds(Number(p.ramp_up) || 0, unit) + toSeconds(Number(p.hold) || 0, unit)
    }
  }
  return 0
}

/**
 * 取所有启用 TG 中等效时长最大的那个（多 TG 并行起跑）。
 */
export function plannedDurationSec(cfgs: ThreadGroupConfig[] | undefined): number {
  if (!cfgs?.length) return 0
  let max = 0
  for (const cfg of cfgs) {
    const sec = tgDurationSec(cfg)
    if (sec > max) max = sec
  }
  return max
}

/**
 * 找第一个 ArrivalsThreadGroup 的 target_rps；没有则返回 null。
 * 用来决定 KPI 卡 2（RPS）的副信息是显示 "/ 500" 还是 "req/s"。
 */
export function targetRps(cfgs: ThreadGroupConfig[] | undefined): number | null {
  if (!cfgs?.length) return null
  for (const cfg of cfgs) {
    if (cfg.kind === 'ArrivalsThreadGroup') {
      const v = Number((cfg.params || {}).target_rps)
      if (v > 0) return v
    }
  }
  return null
}

/**
 * 是否存在至少一个 Arrivals TG（线程数无意义时 KPI 卡 1 显示"—"）。
 */
export function hasOnlyArrivals(cfgs: ThreadGroupConfig[] | undefined): boolean {
  if (!cfgs?.length) return false
  return cfgs.every((c) => c.kind === 'ArrivalsThreadGroup')
}

export function formatDuration(sec: number): string {
  if (!sec || sec <= 0) return '—'
  if (sec < 60) return `${Math.round(sec)} 秒`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  if (m < 60) return s ? `${m} 分 ${s} 秒` : `${m} 分钟`
  const h = Math.floor(m / 60)
  const mm = m % 60
  return mm ? `${h} 小时 ${mm} 分` : `${h} 小时`
}

/**
 * 取 SeriesPoint 数组最后一个点的 value。空数组返回 0。
 */
export function lastValue(series: [number, number][] | undefined): number {
  if (!series || !series.length) return 0
  return series[series.length - 1][1]
}
