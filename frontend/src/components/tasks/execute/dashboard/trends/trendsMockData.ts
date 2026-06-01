/**
 * Trends 末位场景图 —— mock 数据单一来源（临时）。
 *
 * 用途：在「真实数据源接入前」先把 6 个场景 ×2 的末位图前端做出来看效果。
 * `TrendsLayout` 的「🎭 模拟场景数据」开关打开后，整页换成这里生成的一个合成 run：
 *   6 个 ThreadGroup，每个 TG 对应一个场景（基准/负载/压力/稳定性/峰值/吞吐量），
 *   顶部 TG 切换器因此自然出现「全部 / 基准 / …」，跟多分组压测体感一致。
 *
 * 形状严格对齐 `types/task.ts` 现有接口，将来真数据从同一入口换进来即可。
 * ⚠️ 全是编造数据，仅供 UI 预览，不要当真实指标解读。
 */
import type {
  ConcurrencyResponse, RunMetrics, RunMetricsSeries, RunMetricsTotals,
  SamplerStat, ScenarioId, SeriesPoint, TaskRun, TGKind,
} from '@/types/task'

const STEP_MS = 5_000
const N = 120                       // 120 × 5s = 10 分钟窗口
const AVG_RECV_BYTES = 1500
const AVG_SENT_BYTES = 420

// stress 错误时序的桶（跟 ErrorBreakdownStackedChart 的 Bucket 对齐）
export type ErrBucket = '4xx' | '5xx' | 'timeout' | 'connect_error' | 'assertion' | 'other'

interface VerStat { avg: number; p90: number; p99: number }

// 每个场景 mock 出来的完整素材（图① + 图② 都从这里取）
export interface ScenarioMockSpec {
  id: ScenarioId
  label: string
  color: string
  kind: TGKind
  // 图① 用
  rps: SeriesPoint[]
  vu: SeriesPoint[]
  lat: SeriesPoint[]                // p95
  targetRpsPerSec: number | null    // 仅吞吐量
  // 图② 用（按场景只填对应那一个）
  // baseline=null → 只展示本次自己的数据（没设基准 / 自己就是基准）；非空 → 当前 vs 基准对比
  baselineVersions?: { current: VerStat; baseline: VerStat | null; selfIsBaseline?: boolean }
  rtScatter?: { x: number; y: number }[]
  errorBuckets?: Record<ErrBucket, [number, number][]>
  memoryLeak?: { heap: SeriesPoint[]; handles: SeriesPoint[] }
  queueDepth?: SeriesPoint[]
  samplerStats?: SamplerStat[]
}

export interface MockBundle {
  metrics: RunMetrics
  concurrency: ConcurrencyResponse
  run: TaskRun
  xRange: [number, number]
  scenarios: ScenarioMockSpec[]
}

// 确定性伪随机：同一次进程刷新结果稳定，避免每次 computed 重算时曲线乱跳
function mulberry32(seed: number): () => number {
  let s = seed >>> 0
  return () => {
    s = (s + 0x6d2b79f5) | 0
    let t = Math.imul(s ^ (s >>> 15), 1 | s)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

interface Pt { vu: number; rps: number; p50: number; p95: number; p99: number; err: number }

// 各场景在进度 p∈[0,1] 处的形状
function shapeFor(id: ScenarioId): (p: number, rnd: () => number) => Pt {
  switch (id) {
    case 'baseline':
      return (_p, r) => ({
        vu: 10,
        rps: 140 + (r() - 0.5) * 22,
        p50: 110 + (r() - 0.5) * 16,
        p95: 180 + (r() - 0.5) * 26,
        p99: 240 + (r() - 0.5) * 40,
        err: 0,
      })
    case 'load':
      return (p, r) => {
        const vu = Math.round(200 * p)
        const rps = 150 * (1 - Math.exp(-vu / 55)) + (r() - 0.5) * 6
        const p95 = 150 + Math.max(0, vu - 110) * 1.1 + (r() - 0.5) * 14
        return {
          vu,
          rps,
          p50: 90 + Math.max(0, vu - 100) * 0.5,
          p95,
          p99: p95 * 1.4,
          err: vu > 170 ? (vu - 170) * 0.05 : 0,
        }
      }
    case 'stress':
      return (p, r) => {
        const vu = Math.round(500 * p)
        const base = 150 * (1 - Math.exp(-vu / 55))
        const cliff = vu > 320 ? Math.max(0.18, 1 - (vu - 320) / 360) : 1
        const p95 = 130 + Math.max(0, vu - 150) * 1.6 + (vu > 320 ? (vu - 320) * 2.4 : 0)
        return {
          vu,
          rps: base * cliff + (r() - 0.5) * 6,
          p50: 100 + Math.max(0, vu - 150) * 0.8,
          p95,
          p99: p95 * 1.5,
          err: vu > 280 ? (vu - 280) * 0.18 : 0,
        }
      }
    case 'soak':
      return (p, r) => {
        const p95 = 185 + p * 75 + (r() - 0.5) * 16   // 缓慢爬升（泄漏信号）
        return {
          vu: 50,
          rps: 120 + (r() - 0.5) * 14,
          p50: 120 + p * 40,
          p95,
          p99: p95 * 1.4 + p * 30,
          err: r() > 0.95 ? 1 : 0,
        }
      }
    case 'spike':
      return (p, r) => {
        // p∈(0.40,0.60) 区间一个正弦脉冲，峰在 0.50
        let f = 0
        if (p > 0.4 && p < 0.6) f = Math.sin(((p - 0.4) / 0.2) * Math.PI)
        const p95 = 170 + f * 540
        return {
          vu: Math.round(50 + f * 400),
          rps: 140 + f * 300 + (r() - 0.5) * 8,
          p50: 120 + f * 200,
          p95,
          p99: p95 * 1.3,
          err: f > 0.6 ? f * 4 : 0,
        }
      }
    case 'throughput':
    default:
      return (p, r) => {
        const ramp = Math.min(1, p / 0.25)
        const p95 = 150 + ramp * 40 + (r() - 0.5) * 16
        return {
          vu: Math.round(40 + 120 * ramp),
          rps: 200 * ramp * 0.93 + (r() - 0.0) * 4,   // 略低于目标 200
          p50: 110 + ramp * 30,
          p95,
          p99: p95 * 1.4,
          err: 0,
        }
      }
  }
}

const clamp0 = (v: number) => (v > 0 ? v : 0)

function buildSeries(id: ScenarioId, startMs: number, seed: number): RunMetricsSeries {
  const rnd = mulberry32(seed)
  const shape = shapeFor(id)
  const rps: SeriesPoint[] = []
  const p50: SeriesPoint[] = []
  const p95: SeriesPoint[] = []
  const p99: SeriesPoint[] = []
  const errc: SeriesPoint[] = []
  const errr: SeriesPoint[] = []
  const brx: SeriesPoint[] = []
  const btx: SeriesPoint[] = []
  const vu: SeriesPoint[] = []
  for (let i = 0; i < N; i++) {
    const t = startMs + i * STEP_MS
    const pt = shape(i / (N - 1), rnd)
    const r = clamp0(pt.rps)
    const e = clamp0(pt.err)
    rps.push([t, +r.toFixed(1)])
    p50.push([t, Math.round(clamp0(pt.p50))])
    p95.push([t, Math.round(clamp0(pt.p95))])
    p99.push([t, Math.round(clamp0(pt.p99))])
    errc.push([t, +e.toFixed(1)])
    errr.push([t, r > 0 ? +((e / r) * 100).toFixed(2) : 0])
    brx.push([t, Math.round(r * AVG_RECV_BYTES)])
    btx.push([t, Math.round(r * AVG_SENT_BYTES)])
    vu.push([t, Math.round(clamp0(pt.vu))])
  }
  return {
    rps, p50_ms: p50, p95_ms: p95, p99_ms: p99,
    error_rate: errr, error_count: errc,
    bytes_recv: brx, bytes_sent: btx, active_users: vu,
  }
}

function totalsOf(s: RunMetricsSeries): RunMetricsTotals {
  const stepSec = STEP_MS / 1000
  const sum = (pts: SeriesPoint[]) => pts.reduce((a, [, v]) => a + v, 0)
  return {
    total_count: Math.round(sum(s.rps) * stepSec),
    total_errors: Math.round(sum(s.error_count) * stepSec),
    total_bytes_recv: Math.round(sum(s.bytes_recv) * stepSec),
    total_bytes_sent: Math.round(sum(s.bytes_sent) * stepSec),
  }
}

// 把 6 条 TG series 逐点聚合成 overall（rps/err/bytes/vu 求和，分位取各 TG 最大）
function aggregateOverall(all: RunMetricsSeries[]): RunMetricsSeries {
  const out: RunMetricsSeries = {
    rps: [], p50_ms: [], p95_ms: [], p99_ms: [], error_rate: [],
    error_count: [], bytes_recv: [], bytes_sent: [], active_users: [],
  }
  for (let i = 0; i < N; i++) {
    const t = all[0].rps[i][0]
    let rps = 0, errc = 0, brx = 0, btx = 0, vu = 0
    let p50 = 0, p95 = 0, p99 = 0
    for (const s of all) {
      rps += s.rps[i][1]; errc += s.error_count[i][1]
      brx += s.bytes_recv[i][1]; btx += s.bytes_sent[i][1]
      vu += s.active_users[i][1]
      p50 = Math.max(p50, s.p50_ms[i][1])
      p95 = Math.max(p95, s.p95_ms[i][1])
      p99 = Math.max(p99, s.p99_ms[i][1])
    }
    out.rps.push([t, +rps.toFixed(1)])
    out.error_count.push([t, +errc.toFixed(1)])
    out.error_rate.push([t, rps > 0 ? +((errc / rps) * 100).toFixed(2) : 0])
    out.bytes_recv.push([t, brx]); out.bytes_sent.push([t, btx])
    out.active_users.push([t, vu])
    out.p50_ms.push([t, p50]); out.p95_ms.push([t, p95]); out.p99_ms.push([t, p99])
  }
  return out
}

// ── 图② 素材 ───────────────────────────────────────────────────────────

function buildRtScatter(seed: number): { x: number; y: number }[] {
  const rnd = mulberry32(seed)
  const pts: { x: number; y: number }[] = []
  for (let i = 0; i < 130; i++) {
    const vu = Math.round((200 * i) / 130)
    const base = 90 + Math.max(0, vu - 110) * 1.1
    const y = base + (rnd() - 0.5) * 60
    pts.push({ x: vu, y: Math.round(clamp0(y)) })
    if (vu > 120 && rnd() > 0.82) {
      pts.push({ x: vu, y: Math.round(base + 160 + rnd() * 260) })   // 离群点
    }
  }
  return pts
}

function buildErrorBuckets(startMs: number): Record<ErrBucket, [number, number][]> {
  const out: Record<ErrBucket, [number, number][]> = {
    '4xx': [], '5xx': [], timeout: [], connect_error: [], assertion: [], other: [],
  }
  for (let i = 0; i < N; i++) {
    const t = startMs + i * STEP_MS
    const vu = (500 * i) / (N - 1)
    out['4xx'].push([t, vu > 120 ? +(Math.max(0, vu - 120) * 0.02).toFixed(1) : 0])
    out.timeout.push([t, vu > 240 ? +((vu - 240) * 0.05).toFixed(1) : 0])
    out['5xx'].push([t, vu > 300 ? +((vu - 300) * 0.08).toFixed(1) : 0])
    out.connect_error.push([t, vu > 380 ? +((vu - 380) * 0.06).toFixed(1) : 0])
    out.assertion.push([t, vu > 200 ? +((vu - 200) * 0.012).toFixed(1) : 0])
    out.other.push([t, 0])
  }
  return out
}

function buildMemoryLeak(startMs: number, seed: number): { heap: SeriesPoint[]; handles: SeriesPoint[] } {
  const rnd = mulberry32(seed)
  const heap: SeriesPoint[] = []
  const handles: SeriesPoint[] = []
  for (let i = 0; i < N; i++) {
    const t = startMs + i * STEP_MS
    const p = i / (N - 1)
    // 锯齿状缓升（GC 回收 + 总体上扬），句柄单调爬升
    const saw = (i % 12) * 3
    heap.push([t, Math.round(512 + p * 320 + saw + (rnd() - 0.5) * 8)])
    handles.push([t, Math.round(850 + p * 347 + (rnd() - 0.5) * 6)])
  }
  return { heap, handles }
}

function buildQueueDepth(startMs: number): SeriesPoint[] {
  const out: SeriesPoint[] = []
  for (let i = 0; i < N; i++) {
    const t = startMs + i * STEP_MS
    const p = i / (N - 1)
    let depth = 2
    if (p > 0.4 && p < 0.66) {
      const local = (p - 0.4) / 0.26
      depth = 2 + Math.sin(local * Math.PI) * 218   // 脉冲后排队积压，峰 ~220
    }
    out.push([t, Math.round(depth)])
  }
  return out
}

function mkStat(label: string, avg: number, p99: number, rps: number, total: number): SamplerStat {
  return {
    label, total, success: total, error: 0,
    avg_ms: avg, min_ms: Math.round(avg * 0.3), max_ms: Math.round(p99 * 1.6),
    p50_ms: Math.round(avg * 0.85), p90_ms: Math.round(p99 * 0.8), p99_ms: p99,
    avg_rps: rps, avg_bytes: 1500, top_errors: [],
  }
}

function buildSamplerStats(): SamplerStat[] {
  return [
    mkStat('all', 175, 480, 55, 33000),
    mkStat('登录', 270, 1200, 13, 7800),      // 均值最高 + 方差大 → 大泡
    mkStat('查询接口', 116, 240, 14, 8400),
    mkStat('任务列表', 119, 250, 12, 7200),
    mkStat('首页列表', 115, 220, 16, 9600),
  ]
}

// ── 场景定义 + 组装 ─────────────────────────────────────────────────────

const SCENARIO_DEFS: { id: ScenarioId; label: string; color: string; kind: TGKind }[] = [
  { id: 'baseline', label: '基准', color: '#3b82f6', kind: 'ThreadGroup' },
  { id: 'load', label: '负载', color: '#10b981', kind: 'SteppingThreadGroup' },
  { id: 'stress', label: '压力', color: '#f59e0b', kind: 'SteppingThreadGroup' },
  { id: 'soak', label: '稳定性', color: '#8b5cf6', kind: 'ConcurrencyThreadGroup' },
  { id: 'spike', label: '峰值', color: '#ef4444', kind: 'UltimateThreadGroup' },
  { id: 'throughput', label: '吞吐量', color: '#ec4899', kind: 'ArrivalsThreadGroup' },
]

const DURATION_SEC = (N * STEP_MS) / 1000

function plannedParamsFor(id: ScenarioId): Record<string, any> {
  switch (id) {
    case 'baseline': return { users: 10, ramp_up: 5, duration: DURATION_SEC }
    case 'load': return { initial_threads: 0, step_users: 20, step_delay: 50, step_count: 10, hold: 60, shutdown: 5 }
    case 'stress': return { initial_threads: 50, step_users: 50, step_delay: 50, step_count: 9, hold: 60, shutdown: 5 }
    case 'soak': return { target_concurrency: 50, ramp_up: 30, steps: 5, hold: DURATION_SEC, unit: 'S' }
    case 'spike': return { rows: [{ users: 450, initial_delay: 240, ramp_up: 10, hold: 60, shutdown: 10 }] }
    case 'throughput': default: return { target_rps: 200, ramp_up: 150, steps: 10, hold: DURATION_SEC, unit: 'S' }
  }
}

let CACHED: MockBundle | null = null

/** 生成（并缓存）整套 mock 数据。同一进程多次调用返回同一份，曲线稳定不跳。 */
export function buildMockBundle(): MockBundle {
  if (CACHED) return CACHED

  const startMs = Date.now() - N * STEP_MS
  const endMs = startMs + (N - 1) * STEP_MS

  const byTg: Record<string, RunMetricsSeries> = {}
  const totalsByTg: Record<string, RunMetricsTotals> = {}
  const tgPlannedUsers: Record<string, number> = {}
  const tgPlannedMeta: RunMetrics['tg_planned_meta'] = {}
  const scenarios: ScenarioMockSpec[] = []
  const allSeries: RunMetricsSeries[] = []

  SCENARIO_DEFS.forEach((def, idx) => {
    const s = buildSeries(def.id, startMs, 1000 + idx * 97)
    byTg[def.label] = s
    totalsByTg[def.label] = totalsOf(s)
    tgPlannedUsers[def.label] = s.active_users.reduce((m, [, v]) => (v > m ? v : m), 0)
    tgPlannedMeta[def.label] = { kind: def.kind, params: plannedParamsFor(def.id), scenario: def.id }
    allSeries.push(s)

    const spec: ScenarioMockSpec = {
      id: def.id, label: def.label, color: def.color, kind: def.kind,
      rps: s.rps, vu: s.active_users, lat: s.p95_ms,
      targetRpsPerSec: def.id === 'throughput' ? 200 : null,
    }
    if (def.id === 'baseline') {
      spec.baselineVersions = {
        current: { avg: 175, p90: 210, p99: 280 },
        baseline: { avg: 190, p90: 245, p99: 340 },
      }
    } else if (def.id === 'load') {
      spec.rtScatter = buildRtScatter(7 + idx)
    } else if (def.id === 'stress') {
      spec.errorBuckets = buildErrorBuckets(startMs)
    } else if (def.id === 'soak') {
      spec.memoryLeak = buildMemoryLeak(startMs, 31 + idx)
    } else if (def.id === 'spike') {
      spec.queueDepth = buildQueueDepth(startMs)
    } else if (def.id === 'throughput') {
      spec.samplerStats = buildSamplerStats()
    }
    scenarios.push(spec)
  })

  const overall = aggregateOverall(allSeries)
  const totals: RunMetricsTotals = {
    total_count: Object.values(totalsByTg).reduce((a, t) => a + t.total_count, 0),
    total_errors: Object.values(totalsByTg).reduce((a, t) => a + t.total_errors, 0),
    total_bytes_recv: Object.values(totalsByTg).reduce((a, t) => a + t.total_bytes_recv, 0),
    total_bytes_sent: Object.values(totalsByTg).reduce((a, t) => a + t.total_bytes_sent, 0),
  }

  const run = {
    id: -1,
    run_id: 'mockrun0',
    task: -1,
    status: 'success',
    created_at: new Date(startMs - 5000).toISOString(),
    started_at: new Date(startMs).toISOString(),
    finished_at: new Date(endMs).toISOString(),
    virtual_users: tgPlannedUsers['基准'] ?? 10,
    ramp_up_seconds: 5,
    duration_seconds: DURATION_SEC,
    max_wall_sec: DURATION_SEC,
    total_requests: totals.total_count,
    avg_rps: 0,
    p99_ms: 0,
    error_rate: totals.total_count ? (totals.total_errors / totals.total_count) * 100 : 0,
    error_message: '',
    pre_check_log: '',
    runtime_log: '',
    pid: null,
    stop_port: null,
    last_heartbeat_at: null,
    cancel_requested_at: null,
    archived_at: null,
  } as TaskRun

  const metrics: RunMetrics = {
    overall,
    by_tg: byTg,
    by_sampler: {},
    by_sampler_by_tg: {},
    sampler_thread_group: {},
    by_host: {},
    totals,
    totals_by_tg: totalsByTg,
    tg_planned_users: tgPlannedUsers,
    tg_planned_meta: tgPlannedMeta,
    last_ts: new Date(endMs).toISOString(),
    run,
  }

  const concurrency: ConcurrencyResponse = {
    overall: overall.active_users,
    by_tg: Object.fromEntries(
      SCENARIO_DEFS.map((d) => [d.label, byTg[d.label].active_users]),
    ),
  }

  CACHED = { metrics, concurrency, run, xRange: [startMs, endMs], scenarios }
  return CACHED
}
