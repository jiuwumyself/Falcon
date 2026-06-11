<script setup lang="ts">
// Step 4 分析数据：压测「结论报告」。终态数据全走 DB（秒开）。
// 三段式：① 全局头（裁决+整体结论+版本对比+事件轴）② 按线程组(TG)铺开（问题 TG 置顶展开、
// 正常折叠）③ 全局尾（错误分桶/服务瓶颈/Arthas，不区分 TG）。混合压测靠 ② 把问题 TG 揪出来。
import { computed, onMounted, ref, watch } from 'vue'
import {
  CheckCircle2, AlertTriangle, XCircle, Gauge, Activity, Timer, Users,
  AlertOctagon, ListChecks, Stethoscope, Terminal, ChevronDown, ChevronRight, RefreshCw,
  Sparkles, GitCompare, TrendingUp, Flag, Layers, Cpu, Loader2,
} from 'lucide-vue-next'
import { tasksApi, runsApi, ApiError } from '@/lib/api'
import type {
  Task, TaskRun, SamplerStat, ErrorAggregateRow, DiagnosisResponse, ArthasCapture,
  RunEvent, RunMetrics, PrometheusMetricsResponse, SeriesPoint,
} from '@/types/task'
import { buildNarrative, buildTgNarrative } from '@/lib/analyzeNarrative'
import { SEMANTIC } from '@/components/tasks/execute/dashboard/trends/semanticColors'
import { scenarioById, inferScenarioFromKind } from '@/components/tasks/configStageCtx'
import ConcurrencyRpsChart from '@/components/tasks/execute/dashboard/trends/ConcurrencyRpsChart.vue'
import SoakLatencyTrendChart from '@/components/tasks/execute/dashboard/trends/SoakLatencyTrendChart.vue'
import VuRpsDualAxisChart from '@/components/tasks/execute/dashboard/trends/VuRpsDualAxisChart.vue'
import TargetRpsVsActualChart from '@/components/tasks/execute/dashboard/trends/TargetRpsVsActualChart.vue'
import ErrorDonutChart from '@/components/tasks/execute/dashboard/trends/ErrorDonutChart.vue'
import SamplerRtRangeChart from '@/components/tasks/execute/dashboard/trends/SamplerRtRangeChart.vue'
import BaselineVersionBar from '@/components/tasks/execute/dashboard/trends/BaselineVersionBar.vue'
import AnalyzeTgReport from './AnalyzeTgReport.vue'
import MarkdownView from '@/components/MarkdownView.vue'

const props = defineProps<{ task: Task; isDark: boolean }>()
const d = (l: string, dk: string) => (props.isDark ? dk : l)

const TERMINAL = ['success', 'failed', 'timeout', 'cancelled', 'pre_check_failed']

// ── run 选择 ──：下拉只列「打勾保留(keep)」的 run（同 Step 3 历史勾选）；
// allRuns 留全量，给版本对比找基线（基线未必在 keep 列表里）。
const allRuns = ref<TaskRun[]>([])
const runs = ref<TaskRun[]>([])
const selectedRunId = ref<string | null>(null)
const loadingRuns = ref(true)
const selectedRun = computed<TaskRun | null>(
  () => runs.value.find((r) => r.run_id === selectedRunId.value) || null)

async function fetchRuns() {
  loadingRuns.value = true
  try {
    const page = await tasksApi.listRuns(props.task.id)
    allRuns.value = page.results
    runs.value = page.results.filter((r) => r.keep)
    const terminal = runs.value.find((r) => TERMINAL.includes(r.status))
    selectedRunId.value = (terminal || runs.value[0])?.run_id || null
  } catch (e) { console.error('listRuns 失败', e) } finally { loadingRuns.value = false }
}

// ── 该 run 的派生数据 ──
const samplers = ref<SamplerStat[]>([])
const errorRows = ref<ErrorAggregateRow[]>([])
const peakConcurrency = ref<number | null>(null)
const concByTg = ref<Record<string, SeriesPoint[]>>({})
const metrics = ref<RunMetrics | null>(null)
const events = ref<RunEvent[]>([])
const baselineStats = ref<SamplerStat[]>([])
const diagnoses = ref<Record<string, DiagnosisResponse | null>>({})
const cpuPeaks = ref<Record<string, number | null>>({})
const captures = ref<ArthasCapture[]>([])
const loadingData = ref(false)

const services = computed(() => props.task.service_names || [])

async function loadRunData(runId: string) {
  loadingData.value = true
  samplers.value = []; errorRows.value = []; peakConcurrency.value = null; concByTg.value = {}
  metrics.value = null; events.value = []; baselineStats.value = []
  diagnoses.value = {}; cpuPeaks.value = {}; captures.value = []
  try {
    const [s, agg, conc, mtr, evts, caps] = await Promise.all([
      runsApi.samplerStats(runId).catch(() => [] as SamplerStat[]),
      runsApi.errorAggregates(runId).catch(() => ({ aggregates: [], total: 0 })),
      runsApi.concurrency(runId).catch(() => ({ overall: [] as SeriesPoint[], by_tg: {} as Record<string, SeriesPoint[]> })),
      runsApi.metrics(runId).catch(() => null),
      runsApi.events(runId).catch(() => [] as RunEvent[]),
      runsApi.arthasCaptures(runId).catch(() => [] as ArthasCapture[]),
    ])
    samplers.value = s
    errorRows.value = agg.aggregates
    peakConcurrency.value = conc.overall.length ? Math.max(...conc.overall.map((p) => p[1])) : null
    concByTg.value = conc.by_tg || {}
    metrics.value = mtr
    events.value = evts
    captures.value = caps
    const baseId = allRuns.value.find((r) => r.is_baseline && r.run_id !== runId)?.run_id
    if (baseId) runsApi.samplerStats(baseId).then((b) => { baselineStats.value = b }).catch(() => {})
    for (const svc of services.value) {
      runsApi.pinpointDiagnosis(runId, svc, true)
        .then((res) => { diagnoses.value = { ...diagnoses.value, [svc]: res } })
        .catch(() => { diagnoses.value = { ...diagnoses.value, [svc]: null } })
      runsApi.serviceMetrics(runId, svc)
        .then((m) => { cpuPeaks.value = { ...cpuPeaks.value, [svc]: peakOf(m, 'cpu_usage_by_pod') } })
        .catch(() => {})
    }
  } finally { loadingData.value = false }
}

function peakOf(m: PrometheusMetricsResponse, key: string): number | null {
  const series = m[key]
  if (!series) return null
  let max = -Infinity
  for (const p of series.data || []) if (p.value > max) max = p.value
  for (const pod of Object.values(series.pods || {})) for (const p of pod) if (p.value > max) max = p.value
  return max > -Infinity ? max : null
}

watch(selectedRunId, (rid) => { if (rid) { loadRunData(rid); void loadAi(rid) } })
onMounted(fetchRuns)

// ── 全局裁决（纳入 events 早停）──
type Verdict = 'pass' | 'warn' | 'fail'
const earlyAbort = computed(() => events.value.some((e) => e.event_type === 'error_rate_breached'))
const verdict = computed<Verdict>(() => {
  const r = selectedRun.value
  if (!r) return 'warn'
  if (['failed', 'timeout', 'pre_check_failed'].includes(r.status)) return 'fail'
  if (earlyAbort.value) return 'fail'
  const er = r.error_rate ?? 0
  if (er >= 5) return 'fail'
  if (er >= 1 || r.status === 'cancelled') return 'warn'
  return 'pass'
})
const VERDICT_META: Record<Verdict, { label: string; color: string; icon: any }> = {
  pass: { label: '压测通过', color: SEMANTIC.success, icon: CheckCircle2 },
  warn: { label: '需要关注', color: SEMANTIC.latency, icon: AlertTriangle },
  fail: { label: '未通过', color: SEMANTIC.errors, icon: XCircle },
}
const verdictMeta = computed(() => VERDICT_META[verdict.value])
const verdictSummary = computed(() => {
  const r = selectedRun.value
  if (!r) return ''
  const er = (r.error_rate ?? 0).toFixed(2)
  const p99 = fmtMs(r.p99_ms ?? 0)
  if (verdict.value === 'fail') {
    if (earlyAbort.value) return `错误率突破阈值触发早停；P99 ${p99}，服务在该压力下濒临崩溃`
    if (r.status === 'timeout') return `执行超时未正常结束；错误率 ${er}%，P99 ${p99}`
    if (r.status === 'pre_check_failed') return '预检未通过，压测未真正开始'
    return `错误率 ${er}% 偏高、P99 ${p99}，服务在此压力下不可用或濒临崩溃`
  }
  if (verdict.value === 'warn') {
    if (r.status === 'cancelled') return `任务被手动取消；截至取消错误率 ${er}%，P99 ${p99}`
    return `错误率 ${er}% 存在少量失败、P99 ${p99}，建议复核失败接口后再下结论`
  }
  return `错误率 ${er}%、P99 ${p99}，服务在该压力下表现稳定`
})

const peakRps = computed<number | null>(() => {
  const rps = metrics.value?.overall?.rps
  if (!rps?.length) return null
  return Math.max(...rps.map((p) => p[1]))
})

// ── 版本对比 ──
function verOf(stats: SamplerStat[]): { avg: number; p90: number; p99: number } | null {
  const all = stats.find((s) => s.label === 'all') ?? stats[0]
  if (!all) return null
  return { avg: all.avg_ms, p90: all.p90_ms, p99: all.p99_ms }
}
const currentVer = computed(() => verOf(samplers.value))
const selfIsBaseline = computed(() => !!selectedRun.value?.is_baseline)
const baselineVer = computed(() => (selfIsBaseline.value ? null : verOf(baselineStats.value)))

// ── 整体结论 ──
const narrative = computed<string[]>(() => {
  const r = selectedRun.value
  if (!r) return []
  return buildNarrative({
    run: r, samplers: samplers.value, events: events.value,
    serviceFindings: conclusions.value.map((c) => ({ service: c.service, findings: c.findings })),
    peakConcurrency: peakConcurrency.value, peakRps: peakRps.value, baselineP99: baselineVer.value?.p99 ?? null,
  })
})

// ── 整体 KPI ──
const kpis = computed(() => {
  const r = selectedRun.value
  if (!r) return []
  return [
    { label: '总请求', value: fmtNum(r.total_requests ?? 0), icon: ListChecks, danger: false },
    { label: '平均 RPS', value: (r.avg_rps ?? 0).toFixed(1), icon: Activity, danger: false },
    { label: 'P99', value: fmtMs(r.p99_ms ?? 0), icon: Timer, danger: false },
    { label: '错误率', value: `${(r.error_rate ?? 0).toFixed(2)}%`, icon: AlertOctagon, danger: (r.error_rate ?? 0) >= 1 },
    { label: '峰值并发', value: peakConcurrency.value != null ? String(peakConcurrency.value) : '—', icon: Users, danger: false },
    { label: '时长', value: fmtDur(r), icon: Gauge, danger: false },
  ]
})

// ── 按线程组(TG)切分 ──
type Health = 'critical' | 'warn' | 'ok'
const HEALTH_ORDER: Record<Health, number> = { critical: 0, warn: 1, ok: 2 }
const tgKeys = computed(() => (metrics.value?.by_tg ? Object.keys(metrics.value.by_tg) : []))
// 只有「混合（多 TG）」才按 TG 分解；单线程 / 无切分 → 走整体分析。
const multiTg = computed(() => tgKeys.value.length > 1)

function maxOf(series?: SeriesPoint[]): number | null {
  if (!series?.length) return null
  return Math.max(...series.map((p) => p[1]))
}
function tgErrorRate(tg: string): number {
  const t = metrics.value?.totals_by_tg?.[tg]
  return t && t.total_count ? (t.total_errors / t.total_count) * 100 : 0
}
function tgSamplers(tg: string): SamplerStat[] {
  const map = metrics.value?.sampler_thread_group || {}
  return samplers.value.filter((s) => s.label !== 'all' && (map[s.label] || []).includes(tg))
}
function tgErrorRows(tg: string): ErrorAggregateRow[] {
  const map = metrics.value?.sampler_thread_group || {}
  return errorRows.value.filter((e) => (map[e.label] || []).includes(tg))
}
function tgScenario(tg: string): { id: string; label: string; color: string } | null {
  const meta = metrics.value?.tg_planned_meta?.[tg]
  const id = meta?.scenario ?? (meta?.kind ? inferScenarioFromKind(meta.kind) : null)
  if (!id) return null
  const s = scenarioById(id)
  return { id: s.id, label: s.label, color: s.color }
}
// throughput(Arrivals) 场景的目标 RPS：target_rps 是 arrivals/sec，实测 RPS 是 samples/sec，
// 差「该 TG 内 sampler 数」倍，× 后才同尺度（照搬 ScenarioContextChart 的换算）。
function tgTargetRps(tg: string): number | null {
  const meta = metrics.value?.tg_planned_meta?.[tg]
  if (!meta) return null
  const id = meta.scenario ?? inferScenarioFromKind(meta.kind)
  if (id !== 'throughput') return null
  const t = Number(meta.params?.target_rps ?? 0)
  if (!t || t <= 0) return null
  const unit = (meta.params?.unit as string) === 'M' ? 60 : 1
  const map = metrics.value?.sampler_thread_group || {}
  let n = 0
  for (const tgs of Object.values(map)) if (tgs.includes(tg)) n++
  return (t / unit) * (n > 0 ? n : 1)
}
function median(arr: number[]): number {
  const a = arr.filter((x) => x > 0).sort((x, y) => x - y)
  if (!a.length) return 0
  const mid = Math.floor(a.length / 2)
  return a.length % 2 ? a[mid] : (a[mid - 1] + a[mid]) / 2
}

interface TgReport {
  tgName: string
  scenario: { id: string; label: string; color: string } | null
  health: Health
  summary: { errorRate: number; p99: number; peakRps: number | null; peakConcurrency: number | null; totalRequests: number }
  rps: SeriesPoint[]; vu: SeriesPoint[]; lat: SeriesPoint[]; targetRpsPerSec: number | null
  samplers: SamplerStat[]; errorRows: ErrorAggregateRow[]; narrative: string[]
}
const tgReports = computed<TgReport[]>(() => {
  const m = metrics.value
  if (!m?.by_tg) return []
  const keys = Object.keys(m.by_tg)
  const allP99 = keys.map((tg) => maxOf(m.by_tg[tg].p99_ms) ?? 0)
  const med = median(allP99)
  const reports = keys.map((tg): TgReport => {
    const er = tgErrorRate(tg)
    const p99 = maxOf(m.by_tg[tg].p99_ms) ?? 0
    const peakTgRps = maxOf(m.by_tg[tg].rps)
    const peakConc = maxOf(concByTg.value[tg])
    const total = m.totals_by_tg?.[tg]?.total_count ?? 0
    const sp = tgSamplers(tg)
    // 健康判定：错误率 ≥5% 严重；≥1% 关注；P99 显著高于中位数(>2x 且 ≥1s) 关注
    let health: Health = 'ok'
    if (er >= 5) health = 'critical'
    else if (er >= 1) health = 'warn'
    else if (p99 >= 1000 && med > 0 && p99 > med * 2) health = 'warn'
    const scn = tgScenario(tg)
    return {
      tgName: tg, scenario: scn, health,
      summary: { errorRate: er, p99, peakRps: peakTgRps, peakConcurrency: peakConc, totalRequests: total },
      rps: m.by_tg[tg].rps || [], vu: concByTg.value[tg] || [],
      lat: m.by_tg[tg].p95_ms || [], targetRpsPerSec: tgTargetRps(tg),
      samplers: sp, errorRows: tgErrorRows(tg),
      narrative: buildTgNarrative({
        tgName: tg, scenarioLabel: scn?.label || '', errorRate: er, p99,
        peakRps: peakTgRps, peakConcurrency: peakConc, totalRequests: total, samplers: sp,
      }),
    }
  })
  return reports.sort((a, b) =>
    HEALTH_ORDER[a.health] - HEALTH_ORDER[b.health] || b.summary.errorRate - a.summary.errorRate)
})

// 折叠状态：问题 TG 默认展开、正常折叠；单 TG 强制展开。run 数据重载时重置。
const expandedTgs = ref<Set<string>>(new Set())
watch(tgReports, (reports) => {
  const next = new Set<string>()
  if (reports.length === 1) next.add(reports[0].tgName)
  else for (const r of reports) if (r.health !== 'ok') next.add(r.tgName)
  expandedTgs.value = next
})
function toggleTg(name: string) {
  const s = new Set(expandedTgs.value)
  if (s.has(name)) s.delete(name); else s.add(name)
  expandedTgs.value = s
}
const okTgCount = computed(() => tgReports.value.filter((r) => r.health === 'ok').length)

// ── 单线程 / 无切分时的「整体」场景主图分发 ──：单 TG 也要按它的场景给对的图
const soloScenario = computed<{ id: string; label: string; color: string } | null>(() => {
  if (tgKeys.value.length === 1) return tgScenario(tgKeys.value[0])
  const cfg = props.task.thread_groups_config?.[0]
  if (!cfg) return null
  const s = scenarioById(cfg.scenario ?? inferScenarioFromKind(cfg.kind))
  return { id: s.id, label: s.label, color: s.color }
})
const soloRps = computed(() => metrics.value?.overall?.rps || [])
const soloVu = computed(() => metrics.value?.overall?.active_users || [])
const soloLat = computed(() => metrics.value?.overall?.p95_ms || [])
const soloTargetRps = computed(() => (tgKeys.value.length === 1 ? tgTargetRps(tgKeys.value[0]) : null))
const soloUsesConcurrency = computed(() =>
  !soloScenario.value || ['baseline', 'load', 'stress'].includes(soloScenario.value.id))
const soloChartTitle = computed(() => {
  const id = soloScenario.value?.id
  if (id === 'soak') return '延迟趋势（p95 + 回归线，抓泄漏）'
  if (id === 'spike') return 'VU / RPS 双轴跟随'
  if (id === 'throughput') return '目标 vs 实际 RPS'
  return '并发-吞吐关系（自动标拐点）'
})

// ── 整体接口榜（单线程 / 无 TG 切分时用）──
const slowest = computed(() =>
  [...samplers.value].filter((s) => s.label !== 'all').sort((a, b) => b.p99_ms - a.p99_ms).slice(0, 5))
const mostErrors = computed(() =>
  samplers.value.filter((s) => s.label !== 'all' && s.error > 0).sort((a, b) => b.error - a.error).slice(0, 5))
const rtStats = computed(() => samplers.value.filter((s) => s.label !== 'all'))

// ── 错误归因（run 级，不分 TG）──
const errorBreakdown = computed<Record<string, number>>(() => {
  const bd = selectedRun.value?.error_breakdown || {}
  return Object.fromEntries(Object.entries(bd).filter(([, n]) => n > 0))
})
const hasErrors = computed(() => Object.keys(errorBreakdown.value).length > 0 || errorRows.value.length > 0)

// ── 关键事件时间轴（run 级）──
const EVENT_META: Record<string, { label: string; color: string }> = {
  ramp_done: { label: '加压完成', color: SEMANTIC.traffic },
  hold_start: { label: '稳态开始', color: SEMANTIC.success },
  shutdown_start: { label: '开始收尾', color: SEMANTIC.saturation },
  first_sample: { label: '首个样本', color: SEMANTIC.traffic },
  first_error: { label: '首个错误', color: SEMANTIC.errors },
  first_5xx: { label: '首个 5xx', color: SEMANTIC.errors },
  error_rate_breached: { label: '错误率破阈·早停', color: SEMANTIC.errors },
}
const timeline = computed(() => {
  const r = selectedRun.value
  if (!r || !r.started_at) return []
  const start = new Date(r.started_at).getTime()
  const end = r.finished_at ? new Date(r.finished_at).getTime() : Date.now()
  const span = Math.max(1, end - start)
  return events.value
    .filter((e) => EVENT_META[e.event_type])
    .map((e) => ({
      type: e.event_type, ...EVENT_META[e.event_type],
      pct: Math.min(100, Math.max(0, ((e.ts_ms - start) / span) * 100)),
      clock: new Date(e.ts_ms).toLocaleTimeString('zh-CN', { hour12: false }),
    }))
    .sort((a, b) => a.pct - b.pct)
})

// ── 瓶颈定位（按 service，不分 TG）──
interface ServiceConclusion { service: string; loading: boolean; findings: { text: string; sev: 'high' | 'mid' }[] }
const conclusions = computed<ServiceConclusion[]>(() =>
  services.value.map((svc) => {
    const data = diagnoses.value[svc]
    const loaded = svc in diagnoses.value
    const findings: { text: string; sev: 'high' | 'mid' }[] = []
    if (data) {
      const gc = data.jvm?.gc
      if (gc && gc.old_count > 0) findings.push({ text: `Full GC ${gc.old_count} 次 / ${gc.old_time_ms}ms`, sev: 'high' })
      const at = data.active_threads
      if (at && at.max >= 50) findings.push({ text: `活跃线程峰值 ${at.max}`, sev: 'mid' })
      const slow = (data.uri_stat || []).filter((u) => u.max_ms >= 1000)
      if (slow.length) findings.push({ text: `${slow.length} 个慢接口（最慢 ${Math.max(...slow.map((s) => s.max_ms))}ms）`, sev: 'mid' })
      const errs = data.error_uris || []
      if (errs.length) findings.push({ text: `${errs.length} 个失败接口（最多 ×${errs[0]?.fail_count}）`, sev: 'high' })
      const tx = data.transactions
      if (tx && tx.error_rate > 1) findings.push({ text: `服务端错误率 ${tx.error_rate}%`, sev: 'high' })
    }
    return { service: svc, loading: !loaded, findings }
  }))

const expandedCap = ref<number | null>(null)

// ── AI 分析（算法结论之外，调真模型；密钥在后端，前端只触发）──
const aiSummary = ref('')
const aiMeta = ref<Record<string, any>>({})
const aiConfigured = ref(true)
const aiLoading = ref(false)
const aiError = ref('')
async function loadAi(runId: string) {
  aiSummary.value = ''; aiMeta.value = {}; aiError.value = ''
  try {
    const r = await runsApi.aiSummary(runId)
    aiSummary.value = r.summary; aiMeta.value = r.meta || {}; aiConfigured.value = r.configured
  } catch { /* 读缓存失败忽略 */ }
}
async function genAi() {
  if (!selectedRunId.value || aiLoading.value) return
  aiLoading.value = true; aiError.value = ''
  try {
    const r = await runsApi.generateAiSummary(selectedRunId.value)
    aiSummary.value = r.summary; aiMeta.value = r.meta || {}; aiConfigured.value = true
  } catch (e) {
    aiError.value = e instanceof ApiError ? e.humanMessage : String(e)
  } finally { aiLoading.value = false }
}

// ── 工具 ──
function fmtMs(v: number) { return v >= 1000 ? (v / 1000).toFixed(2) + 's' : Math.round(v) + 'ms' }
function fmtNum(v: number) { return v >= 10000 ? (v / 1000).toFixed(1) + 'k' : String(v) }
function fmtDur(r: TaskRun) {
  if (!r.started_at) return '—'
  const end = r.finished_at ? new Date(r.finished_at).getTime() : Date.now()
  const sec = Math.max(0, Math.round((end - new Date(r.started_at).getTime()) / 1000))
  const m = Math.floor(sec / 60), s = sec % 60
  return m ? `${m}m${s}s` : `${s}s`
}
function fmtTime(s: string) { return new Date(s).toLocaleString('zh-CN', { hour12: false }).slice(5) }

const card = computed(() => ({
  background: props.isDark ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.6)',
  border: `1px solid ${props.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
}))
const RUN_LABEL: Record<string, string> = {
  success: '成功', failed: '失败', timeout: '超时', cancelled: '已取消',
  pre_check_failed: '预检失败', running: '运行中', pending: '排队', pre_checking: '预检中', cancelling: '取消中',
}
</script>

<template>
  <div class="h-full min-h-0 overflow-y-auto">
    <div class="p-4 space-y-3 max-w-[1080px] mx-auto">
      <!-- 顶部：run 选择 -->
      <div class="flex items-center justify-between gap-2">
        <h2 class="text-[15px] font-semibold m-0" :style="{ color: d('#1a1a2e', '#fff') }">压测分析报告</h2>
        <div class="flex items-center gap-2">
          <span class="text-[10px]" :style="{ color: d('rgba(0,0,0,0.35)', 'rgba(255,255,255,0.35)') }">选择记录</span>
          <select v-model="selectedRunId" class="text-[12px] px-2 py-1 rounded-md outline-none cursor-pointer"
                  :style="{ background: d('rgba(0,0,0,0.04)', 'rgba(255,255,255,0.06)'), color: d('#1a1a2e', '#fff'), border: `1px solid ${d('rgba(0,0,0,0.08)', 'rgba(255,255,255,0.1)')}` }">
            <option v-for="r in runs" :key="r.run_id" :value="r.run_id"
                    :style="{ background: d('#fff', '#1a2330'), color: d('#1a1a2e', '#fff') }">
              {{ r.run_id.slice(0, 8) }} · {{ RUN_LABEL[r.status] || r.status }} · {{ fmtTime(r.created_at) }}
            </option>
          </select>
          <button v-if="selectedRunId" class="p-1 rounded-md" title="刷新"
                  :style="{ color: d('rgba(0,0,0,0.5)', 'rgba(255,255,255,0.5)') }"
                  @click="loadRunData(selectedRunId)">
            <RefreshCw :size="13" :class="loadingData ? 'animate-spin' : ''" />
          </button>
        </div>
      </div>

      <!-- 空态 -->
      <div v-if="loadingRuns" class="text-[12px] py-16 text-center" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">加载中…</div>
      <div v-else-if="!allRuns.length" class="text-[12px] py-16 text-center" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">
        <Gauge :size="22" class="inline-block mb-2" /><br>还没有压测记录，先去 <b>Step 3 执行任务</b> 跑一次。
      </div>
      <div v-else-if="!runs.length" class="text-[12px] py-16 text-center" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">
        <Gauge :size="22" class="inline-block mb-2" /><br>还没有「打勾保留」的记录。<br>去 <b>Step 3 执行任务</b> 的历史列表里勾选要分析的 run（只有打勾保留的记录才会出现在这里）。
      </div>

      <template v-else-if="selectedRun">
        <!-- ① 全局头：裁决 + 整体结论 -->
        <div class="rounded-xl overflow-hidden" :style="{ border: `1px solid ${verdictMeta.color}40` }">
          <div class="flex items-start gap-3 p-4" :style="{ background: `${verdictMeta.color}14` }">
            <component :is="verdictMeta.icon" :size="26" :color="verdictMeta.color" class="flex-shrink-0 mt-0.5" />
            <div class="min-w-0">
              <p class="text-[16px] font-semibold m-0" :style="{ color: verdictMeta.color }">{{ verdictMeta.label }}</p>
              <p class="text-[12px] mt-0.5 m-0" :style="{ color: d('rgba(0,0,0,0.65)', 'rgba(255,255,255,0.7)') }">{{ verdictSummary }}</p>
            </div>
          </div>
          <div class="px-4 py-3" :style="{ background: d('rgba(255,255,255,0.5)', 'rgba(255,255,255,0.015)') }">
            <div class="flex items-center justify-between gap-2 mb-1.5">
              <span class="text-[10px] px-1.5 py-0.5 rounded inline-flex items-center gap-1"
                    :style="{ background: d('rgba(0,0,0,0.05)', 'rgba(255,255,255,0.08)'), color: d('rgba(0,0,0,0.5)', 'rgba(255,255,255,0.5)') }">
                <Cpu :size="10" />算法结论
              </span>
              <button class="text-[11px] px-2.5 py-1 rounded-md inline-flex items-center gap-1 font-medium"
                      :style="{
                        background: aiLoading ? d('rgba(0,0,0,0.06)', 'rgba(255,255,255,0.08)') : 'linear-gradient(90deg,#8b5cf6,#6366f1)',
                        color: aiLoading ? d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') : '#fff',
                        cursor: aiLoading ? 'default' : 'pointer',
                      }"
                      :disabled="aiLoading" @click="genAi">
                <component :is="aiLoading ? Loader2 : Sparkles" :size="12" :class="aiLoading ? 'animate-spin' : ''" />
                {{ aiLoading ? 'AI 分析中…' : (aiSummary ? '重新 AI 分析' : 'AI 分析') }}
              </button>
            </div>
            <ul v-if="narrative.length" class="space-y-1 m-0 pl-0 list-none">
              <li v-for="(line, i) in narrative" :key="i" class="text-[12px] leading-relaxed flex gap-1.5"
                  :style="{ color: d('rgba(0,0,0,0.72)', 'rgba(255,255,255,0.75)') }">
                <span :style="{ color: verdictMeta.color }">·</span><span>{{ line }}</span>
              </li>
            </ul>
            <!-- AI 分析结果 -->
            <div v-if="aiError" class="mt-2 text-[11px] px-2 py-1.5 rounded"
                 :style="{ background: 'rgba(239,68,68,0.1)', color: SEMANTIC.errors }">{{ aiError }}</div>
            <div v-else-if="aiSummary" class="mt-2 pt-2" :style="{ borderTop: `1px solid ${d('rgba(0,0,0,0.08)', 'rgba(255,255,255,0.08)')}` }">
              <span class="text-[10px] px-1.5 py-0.5 rounded inline-flex items-center gap-1"
                    :style="{ background: 'rgba(139,92,246,0.12)', color: '#8b5cf6' }">
                <Sparkles :size="10" />AI 分析<template v-if="aiMeta.model"> · {{ aiMeta.model }}</template>
              </span>
              <MarkdownView :source="aiSummary" :is-dark="isDark" class="mt-1.5" />
            </div>
          </div>
        </div>

        <!-- 整体 KPI -->
        <div class="grid grid-cols-3 sm:grid-cols-6 gap-2">
          <div v-for="k in kpis" :key="k.label" class="p-2.5 rounded-xl" :style="card">
            <div class="flex items-center gap-1 text-[10px] mb-1" :style="{ color: d('rgba(0,0,0,0.45)', 'rgba(255,255,255,0.45)') }">
              <component :is="k.icon" :size="11" />{{ k.label }}
            </div>
            <p class="text-[17px] font-semibold m-0 tabular-nums"
               :style="{ color: k.danger ? SEMANTIC.errors : d('#1a1a2e', '#fff') }">{{ k.value }}</p>
          </div>
        </div>

        <!-- 版本对比 + 事件轴 -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div class="p-3 rounded-xl" :style="card">
            <p class="text-[12px] font-medium mb-1 flex items-center gap-1.5" :style="{ color: d('#1a1a2e', '#fff') }">
              <GitCompare :size="13" :color="SEMANTIC.traffic" />版本基准对比
            </p>
            <div style="height:200px">
              <BaselineVersionBar v-if="currentVer" :current="currentVer" :baseline="baselineVer" :self-is-baseline="selfIsBaseline" :is-dark="isDark" />
              <p v-else class="text-[11px] py-10 text-center" :style="{ color: d('rgba(0,0,0,0.35)', 'rgba(255,255,255,0.35)') }">无接口统计数据</p>
            </div>
          </div>
          <div class="p-3 rounded-xl" :style="card">
            <p class="text-[12px] font-medium mb-3 flex items-center gap-1.5" :style="{ color: d('#1a1a2e', '#fff') }">
              <Flag :size="13" :color="SEMANTIC.latency" />关键事件时间轴
            </p>
            <div v-if="timeline.length">
              <div class="relative h-9 mx-1">
                <div class="absolute left-0 right-0 top-1/2 h-px" :style="{ background: d('rgba(0,0,0,0.12)', 'rgba(255,255,255,0.12)') }" />
                <div v-for="(ev, i) in timeline" :key="i" class="absolute top-1/2 -translate-y-1/2 -translate-x-1/2"
                     :style="{ left: `${ev.pct}%` }" :title="`${ev.label} · ${ev.clock}`">
                  <span class="block w-2.5 h-2.5 rounded-full" :style="{ background: ev.color, boxShadow: `0 0 0 3px ${ev.color}22` }" />
                </div>
              </div>
              <div class="flex flex-wrap gap-x-3 gap-y-1 mt-1">
                <span v-for="(ev, i) in timeline" :key="i" class="inline-flex items-center gap-1 text-[10px]"
                      :style="{ color: d('rgba(0,0,0,0.55)', 'rgba(255,255,255,0.55)') }">
                  <span class="w-2 h-2 rounded-full" :style="{ background: ev.color }" />{{ ev.label }} <span :style="{ color: d('rgba(0,0,0,0.35)', 'rgba(255,255,255,0.35)') }">{{ ev.clock }}</span>
                </span>
              </div>
            </div>
            <p v-else class="text-[11px] py-8 text-center" :style="{ color: d('rgba(0,0,0,0.35)', 'rgba(255,255,255,0.35)') }">无关键事件记录</p>
          </div>
        </div>

        <!-- ② 混合（多 TG）→ 按线程组铺开 -->
        <template v-if="multiTg">
          <div class="flex items-center gap-2 pt-1">
            <Layers :size="14" :color="SEMANTIC.saturation" />
            <span class="text-[13px] font-semibold" :style="{ color: d('#1a1a2e', '#fff') }">按线程组分解</span>
            <span class="text-[10px]" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">
              {{ tgKeys.length }} 个 TG<template v-if="tgKeys.length > 1 && okTgCount">，{{ okTgCount }} 个正常已折叠</template>
            </span>
          </div>
          <AnalyzeTgReport
            v-for="r in tgReports" :key="r.tgName"
            :tg-name="r.tgName" :scenario="r.scenario" :health="r.health" :summary="r.summary"
            :rps="r.rps" :vu="r.vu" :lat="r.lat" :target-rps-per-sec="r.targetRpsPerSec"
            :samplers="r.samplers" :error-rows="r.errorRows" :narrative="r.narrative"
            :expanded="expandedTgs.has(r.tgName)" :is-dark="isDark"
            @toggle="toggleTg(r.tgName)"
          />
        </template>

        <!-- 单线程 / 无 TG 切分 → 整体数据分析（容量图 + 红黑榜 + RT 图）-->
        <template v-else>
          <div class="p-3 rounded-xl" :style="card">
            <p class="text-[12px] font-medium mb-1 flex items-center gap-1.5" :style="{ color: d('#1a1a2e', '#fff') }">
              <TrendingUp :size="13" :color="SEMANTIC.saturation" />{{ soloChartTitle }}
              <span v-if="soloScenario" class="text-[10px] px-1.5 py-0.5 rounded font-normal" :style="{ background: soloScenario.color + '1f', color: soloScenario.color }">{{ soloScenario.label }}</span>
            </p>
            <div style="height:220px">
              <ConcurrencyRpsChart v-if="soloUsesConcurrency" :rps="soloRps" :vu="soloVu" :is-dark="isDark" />
              <SoakLatencyTrendChart v-else-if="soloScenario?.id === 'soak'" :lat="soloLat" :x-range="null" :is-dark="isDark" />
              <VuRpsDualAxisChart v-else-if="soloScenario?.id === 'spike'" :rps="soloRps" :vu="soloVu" :x-range="null" :is-dark="isDark" />
              <TargetRpsVsActualChart v-else-if="soloScenario?.id === 'throughput'" :rps="soloRps" :target-rps-per-sec="soloTargetRps" :x-range="null" :is-dark="isDark" />
            </div>
          </div>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div class="p-3 rounded-xl" :style="card">
              <p class="text-[12px] font-medium mb-2 flex items-center gap-1.5" :style="{ color: d('#1a1a2e', '#fff') }">
                <Timer :size="13" :color="SEMANTIC.latency" />最慢接口 <span class="text-[10px] font-normal" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">按 P99</span>
              </p>
              <p v-if="!slowest.length" class="text-[11px] py-3 text-center" :style="{ color: d('rgba(0,0,0,0.35)', 'rgba(255,255,255,0.35)') }">无接口数据</p>
              <div v-for="s in slowest" :key="s.label" class="flex items-center gap-2 py-1 text-[11px]">
                <span class="flex-1 min-w-0 truncate" :style="{ color: d('rgba(0,0,0,0.75)', 'rgba(255,255,255,0.75)') }" :title="s.label">{{ s.label }}</span>
                <span class="tabular-nums font-medium" :style="{ color: s.p99_ms >= 1000 ? SEMANTIC.errors : d('#1a1a2e', '#fff') }">{{ fmtMs(s.p99_ms) }}</span>
              </div>
            </div>
            <div class="p-3 rounded-xl" :style="card">
              <p class="text-[12px] font-medium mb-2 flex items-center gap-1.5" :style="{ color: d('#1a1a2e', '#fff') }">
                <AlertOctagon :size="13" :color="SEMANTIC.errors" />报错最多接口
              </p>
              <p v-if="!mostErrors.length" class="text-[11px] py-3 text-center" :style="{ color: d('rgba(0,0,0,0.35)', 'rgba(255,255,255,0.35)') }">无失败接口 🎉</p>
              <div v-for="s in mostErrors" :key="s.label" class="flex items-center gap-2 py-1 text-[11px]">
                <span class="flex-1 min-w-0 truncate" :style="{ color: d('rgba(0,0,0,0.75)', 'rgba(255,255,255,0.75)') }" :title="s.label">{{ s.label }}</span>
                <span class="tabular-nums font-medium" :style="{ color: SEMANTIC.errors }">×{{ s.error }}</span>
              </div>
            </div>
          </div>
          <div v-if="rtStats.length" class="p-3 rounded-xl" :style="card">
            <p class="text-[12px] font-medium mb-1 flex items-center gap-1.5" :style="{ color: d('#1a1a2e', '#fff') }">
              <Activity :size="13" :color="SEMANTIC.latency" />接口响应时间分布 <span class="text-[10px] font-normal" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">min / avg / p99</span>
            </p>
            <div :style="{ height: `${Math.max(140, Math.min(rtStats.length, 12) * 26 + 40)}px` }">
              <SamplerRtRangeChart :stats="rtStats" :is-dark="isDark" />
            </div>
          </div>
        </template>

        <!-- ③ 全局尾：错误归因 / 服务瓶颈 / Arthas（不区分 TG）-->
        <div v-if="hasErrors" class="p-3 rounded-xl" :style="card">
          <p class="text-[12px] font-medium mb-2 flex items-center gap-1.5" :style="{ color: d('#1a1a2e', '#fff') }">
            <AlertTriangle :size="13" :color="SEMANTIC.latency" />错误归因
            <span class="text-[10px] font-normal" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">含全部 TG 合计</span>
          </p>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div v-if="Object.keys(errorBreakdown).length" style="height:180px">
              <ErrorDonutChart :breakdown="errorBreakdown" :is-dark="isDark" />
            </div>
            <div v-if="errorRows.length" class="space-y-1">
              <p class="text-[10px] mb-1" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">代表错误</p>
              <div v-for="(e, i) in errorRows.slice(0, 6)" :key="i" class="flex items-start gap-2 text-[11px] py-0.5">
                <span class="px-1.5 rounded text-[10px] font-mono flex-shrink-0" :style="{ background: d('rgba(239,68,68,0.1)', 'rgba(239,68,68,0.18)'), color: SEMANTIC.errors }">{{ e.response_code || '—' }}</span>
                <span class="flex-1 min-w-0 truncate" :style="{ color: d('rgba(0,0,0,0.7)', 'rgba(255,255,255,0.7)') }" :title="e.sample_message || e.sample_failure_message">{{ e.sample_message || e.sample_failure_message || e.label }}</span>
                <span class="tabular-nums flex-shrink-0" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">×{{ e.count }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="p-3 rounded-xl" :style="card">
          <p class="text-[12px] font-medium mb-2 flex items-center gap-1.5" :style="{ color: d('#1a1a2e', '#fff') }">
            <Stethoscope :size="13" :color="SEMANTIC.saturation" />瓶颈定位 <span class="text-[10px] font-normal" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">按服务诊断 · 不区分 TG</span>
          </p>
          <p v-if="!services.length" class="text-[11px] py-3 text-center" :style="{ color: d('rgba(0,0,0,0.35)', 'rgba(255,255,255,0.35)') }">Step 2 未选择被压测服务，无服务级诊断。</p>
          <div v-for="c in conclusions" :key="c.service" class="py-1.5"
               :style="{ borderTop: `1px solid ${d('rgba(0,0,0,0.05)', 'rgba(255,255,255,0.05)')}` }">
            <div class="flex items-center gap-2 mb-1 flex-wrap">
              <span class="text-[12px] font-medium" :style="{ color: d('#1a1a2e', '#fff') }">{{ c.service }}</span>
              <span v-if="cpuPeaks[c.service] != null" class="text-[10px] px-1.5 rounded tabular-nums"
                    :style="{ background: d('rgba(0,0,0,0.04)', 'rgba(255,255,255,0.06)'), color: d('rgba(0,0,0,0.55)', 'rgba(255,255,255,0.55)') }">CPU 峰值 {{ cpuPeaks[c.service]!.toFixed(0) }}%</span>
              <span v-if="c.loading" class="text-[10px]" :style="{ color: d('rgba(0,0,0,0.35)', 'rgba(255,255,255,0.35)') }">诊断中…</span>
              <span v-else-if="!c.findings.length" class="text-[10px] px-1.5 rounded" :style="{ background: 'rgba(16,185,129,0.12)', color: SEMANTIC.success }">未发现明显异常</span>
            </div>
            <div class="flex flex-wrap gap-1.5">
              <span v-for="(f, i) in c.findings" :key="i" class="text-[11px] px-2 py-0.5 rounded"
                    :style="{ background: f.sev === 'high' ? 'rgba(239,68,68,0.1)' : 'rgba(245,158,11,0.1)', color: f.sev === 'high' ? SEMANTIC.errors : SEMANTIC.latency }">{{ f.text }}</span>
            </div>
          </div>
        </div>

        <div v-if="captures.length" class="p-3 rounded-xl" :style="card">
          <p class="text-[12px] font-medium mb-2 flex items-center gap-1.5" :style="{ color: d('#1a1a2e', '#fff') }">
            <Terminal :size="13" :color="SEMANTIC.success" />Arthas 实锤 <span class="text-[10px] font-normal" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">{{ captures.length }} 条</span>
          </p>
          <div v-for="cap in captures" :key="cap.id"
               :style="{ borderTop: `1px solid ${d('rgba(0,0,0,0.05)', 'rgba(255,255,255,0.05)')}` }">
            <button class="w-full flex items-center gap-2 py-1.5 text-left text-[11px]"
                    @click="expandedCap = expandedCap === cap.id ? null : cap.id">
              <component :is="expandedCap === cap.id ? ChevronDown : ChevronRight" :size="12" :color="d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)')" />
              <span class="font-mono px-1.5 rounded flex-shrink-0" :style="{ background: d('rgba(0,0,0,0.05)', 'rgba(255,255,255,0.06)'), color: d('#1a1a2e', '#fff') }">{{ cap.command }}</span>
              <span v-if="cap.service" class="text-[10px] flex-shrink-0" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">{{ cap.service }}</span>
              <span v-if="cap.note" class="flex-1 min-w-0 truncate" :style="{ color: SEMANTIC.latency }">{{ cap.note }}</span>
              <span class="ml-auto text-[10px] flex-shrink-0" :style="{ color: d('rgba(0,0,0,0.3)', 'rgba(255,255,255,0.3)') }">{{ fmtTime(cap.created_at) }}</span>
            </button>
            <pre v-if="expandedCap === cap.id" class="text-[10px] leading-relaxed p-2 rounded-md overflow-x-auto mb-1.5 whitespace-pre-wrap"
                 :style="{ background: d('rgba(0,0,0,0.04)', 'rgba(0,0,0,0.3)'), color: d('rgba(0,0,0,0.75)', 'rgba(255,255,255,0.75)') }">{{ cap.output || '（无输出）' }}</pre>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>
