// 按 TG kind + params 算"计划用户曲线"——含 ramp-up 渐增 / hold 平台 / shutdown 下降。
// 用途：执行页 ConcurrencyChart 在单 TG 选中时，per-TG 实测并发 JMeter listener 拿不到
// （maxAT 是全局值），用计划曲线替代静态平线，至少能看到 ramp 启动波动。
//
// 实现移植自 components/tasks/config/ThreadGroupChart.vue 的 rawPoints 计算。
// 这边比 ThreadGroupChart 多一步：把"相对秒"映射到真实 epoch ms 时间戳，并按
// 1 秒一个点的密度采样（让 ThroughputPerVuChart 的 vu/rps 时间戳能对齐）。

import type { SeriesPoint, TGKind } from '@/types/task'

interface RawPoint { t: number; y: number }

function toNum(v: unknown, fb = 0): number {
  const n = typeof v === 'string' ? Number(v) : (v as number)
  return Number.isFinite(n) ? n : fb
}

// 生成 (相对秒, 活跃 VU) 折线锚点（不密采样，只是关键拐点）
function rawPoints(kind: TGKind, params: Record<string, any>): RawPoint[] {
  const p = params || {}
  if (kind === 'ThreadGroup') {
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
  if (kind === 'SteppingThreadGroup') {
    const initial = toNum(p.initial_threads, 0)
    const stepU = toNum(p.step_users, 10)
    const stepD = Math.max(1, toNum(p.step_delay, 30))
    const stepC = Math.max(0, toNum(p.step_count, 10))
    const hold = toNum(p.hold, 60)
    const shutdown = Math.max(0, toNum(p.shutdown, 1))

    const pts: RawPoint[] = [{ t: 0, y: 0 }]
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
  if (kind === 'ConcurrencyThreadGroup' || kind === 'ArrivalsThreadGroup') {
    const target = kind === 'ConcurrencyThreadGroup'
      ? toNum(p.target_concurrency, 100)
      : toNum(p.target_rps, 500)
    const ramp = Math.max(0, toNum(p.ramp_up, 10))
    const steps = Math.max(0, toNum(p.steps, 5))
    const hold = toNum(p.hold, 60)
    const unit = (p.unit as string) === 'M' ? 60 : 1
    const holdSec = hold * unit

    const pts: RawPoint[] = [{ t: 0, y: 0 }]
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
  if (kind === 'UltimateThreadGroup') {
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
}

// 在两个锚点之间用线性插值（计划值都是线性 ramp / step / hold，没曲线）
function interpAt(anchors: RawPoint[], t: number): number {
  if (!anchors.length) return 0
  if (t <= anchors[0].t) return anchors[0].y
  for (let i = 1; i < anchors.length; i++) {
    const a = anchors[i - 1]
    const b = anchors[i]
    if (t >= a.t && t <= b.t) {
      if (b.t === a.t) return b.y
      return a.y + (b.y - a.y) * (t - a.t) / (b.t - a.t)
    }
  }
  return anchors[anchors.length - 1].y
}

/**
 * 按真实 epoch ms 时间戳生成 per-TG 计划并发曲线。
 *
 * @param kind        TG 类型（ThreadGroup / SteppingThreadGroup / ...）
 * @param params      TG 配置参数
 * @param startMs     run 启动时刻（epoch ms），曲线相对秒从这里算
 * @param endMs       采样终点（已结束 run 用 finished_at；运行中用 Date.now()）
 * @param stepMs      采样密度，默认 1000ms 一个点
 * @returns           SeriesPoint[]，[[ts, planned_users], ...]
 */
export function plannedCurve(
  kind: TGKind,
  params: Record<string, any>,
  startMs: number,
  endMs: number,
  stepMs = 1000,
): SeriesPoint[] {
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) {
    return []
  }
  const anchors = rawPoints(kind, params)
  if (!anchors.length) return []

  const out: SeriesPoint[] = []
  for (let ts = startMs; ts <= endMs; ts += stepMs) {
    const relSec = (ts - startMs) / 1000
    out.push([ts, interpAt(anchors, relSec)])
  }
  // 兜底：保证至少 2 个点（避免单点 echarts 渲染失败）
  if (out.length === 1) out.push([endMs, out[0][1]])
  return out
}

/**
 * 按 rps series 的时间戳逐点对齐生成 planned 曲线（不按固定 stepMs 采样）。
 * 用途：ThroughputPerVuChart 用 vu 时间戳查 rps map，时间戳必须 1:1 对齐才能算
 * 出非零的 rps/vu 比值。
 */
export function plannedCurveAlignedToTimestamps(
  kind: TGKind,
  params: Record<string, any>,
  startMs: number,
  timestamps: number[],
): SeriesPoint[] {
  if (!Number.isFinite(startMs) || !timestamps.length) return []
  const anchors = rawPoints(kind, params)
  if (!anchors.length) return []
  return timestamps.map((ts) => {
    const relSec = (ts - startMs) / 1000
    return [ts, interpAt(anchors, relSec)] as SeriesPoint
  })
}
