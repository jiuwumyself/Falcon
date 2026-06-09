import type {
  ConcurrencyResponse, Environment, ErrorAggregatesResponse, ErrorSamplesQuery,
  ErrorSamplesResponse, FluentBitMetricsResponse, LatencyBreakdownResponse, LoadGenerator,
  Paginated, PinpointTrace, PrometheusDataSource, PrometheusMetricsResponse,
  ArthasCapture, DiagnosisResponse,
  PrometheusServiceList, RunEvent, RunMetrics, SamplerStat, ServerMapResponse,
  Service, Task, TaskRun,
} from '@/types/task'

// /api/performance/ is the current backend module prefix. When other modules
// (ui, apitest, ...) ship we'll split this into per-module helpers — for now a
// single constant covers every call we have.
const BASE = '/api/performance'

export class ApiError extends Error {
  status: number
  body: string
  humanMessage: string
  constructor(status: number, body: string) {
    const human = formatDrfError(body, status)
    super(`${status}: ${human}`)
    this.status = status
    this.body = body
    this.humanMessage = human
  }
}

/**
 * DRF 的 400 错误体长这样：
 *   {"jmx_file": ["仅支持 .jmx 文件"], "title": ["此字段为必填项。"]}
 * 或
 *   {"detail": "Not found."}
 * 或纯字符串、HTML（500 错误页）。
 * 把它们统一压成一行可读文案。
 */
function formatDrfError(body: string, status: number): string {
  const text = (body ?? '').trim()
  if (!text) return `HTTP ${status}`

  // Try to parse as JSON
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    // Not JSON — likely HTML 500 page or plain text. Truncate heavy payloads.
    return text.length > 200 ? text.slice(0, 200) + '…' : text
  }

  if (typeof parsed === 'string') return parsed
  if (!parsed || typeof parsed !== 'object') return text

  const obj = parsed as Record<string, unknown>
  // DRF's generic "not found / permission denied" shape: { detail: "..." }
  if (typeof obj.detail === 'string') return obj.detail

  // Field errors: {field: ["msg1", "msg2"], ...}  or  {field: "msg"}
  const parts: string[] = []
  for (const [field, val] of Object.entries(obj)) {
    const msgs = Array.isArray(val) ? val.map(String) : [String(val)]
    const joined = msgs.join('; ')
    // Non-field errors → show message only
    parts.push(
      field === 'non_field_errors' || field === 'detail'
        ? joined
        : `${field}: ${joined}`
    )
  }
  return parts.join(' · ') || text
}

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (!headers.has('Content-Type') && init.body && typeof init.body === 'string') {
    headers.set('Content-Type', 'application/json')
  }
  const res = await fetch(`${BASE}${path}`, { ...init, headers })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new ApiError(res.status, body)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export function apiForm<T = unknown>(path: string, form: FormData, method = 'POST'): Promise<T> {
  // Don't set Content-Type — browser sets multipart boundary automatically.
  return api<T>(path, { method, body: form })
}

// ─── Tasks API ─────────────────────────────────────────────────────────
// 集中常用的 task 操作，避免组件里散落 fetch 字符串。
export const tasksApi = {
  list: () => api<Paginated<Task>>('/tasks/'),
  get: (id: number) => api<Task>(`/tasks/${id}/`),
  // 通用 PATCH：用于 service_name 等 Task 直属字段的轻改动；线程组配置仍走专用 thread-groups 端点
  update: (id: number, patch: Partial<Task>) =>
    api<Task>(`/tasks/${id}/`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  delete: (id: number) =>
    api<void>(`/tasks/${id}/`, { method: 'DELETE' }),
  uploadComponentCsv: (id: number, componentPath: string, file: File) => {
    const fd = new FormData()
    fd.append('path', componentPath)
    fd.append('csv_file', file)
    return apiForm<Task>(`/tasks/${id}/components/upload-csv/`, fd)
  },
  deleteComponentCsv: (id: number, componentPath: string) =>
    api<Task>(`/tasks/${id}/components/delete-csv/`, {
      method: 'POST',
      body: JSON.stringify({ path: componentPath }),
    }),
  // 跑压测前在内存里组装的可执行 XML（套 Step 2 thread_groups + CSV 绝对路径
  // + Environment DNSCacheManager 注入 + BackendListener 注入）。仅预览，不写盘。
  previewRunXml: (id: number) =>
    api<{ xml: string }>(`/tasks/${id}/preview-run-xml/`),
  // Step 3: 触发 run + 拉历史 run 列表
  // v1.2：可选传 load_generator_ids 走多机调度；省略 → 单机本地兜底
  startRun: (id: number, opts: { load_generator_ids?: number[] } = {}) =>
    api<TaskRun>(`/tasks/${id}/run/`, {
      method: 'POST',
      body: JSON.stringify(opts),
    }),
  listRuns: (id: number) => api<Paginated<TaskRun>>(`/tasks/${id}/runs/`),
  // 只读 Environment 列表（编辑走 admin），给 RunPlanSummary 显示环境名 + hosts 数用
  environments: () => api<Environment[]>('/environments/'),

  // ── 服务诊断（task 级，脱离 run）：不压测时按时间窗看实时 Pinpoint/Prometheus ──
  serviceDiagnosis: (taskId: number, service: string, brief = false, win?: { from: number; to: number }): Promise<DiagnosisResponse> => {
    const w = win ? `&from=${win.from}&to=${win.to}` : ''
    return api<DiagnosisResponse>(`/tasks/${taskId}/service-diagnosis/?service=${encodeURIComponent(service)}${brief ? '&brief=1' : ''}${w}`)
  },
  serviceServermap: (taskId: number, service: string, win?: { from: number; to: number }): Promise<ServerMapResponse> => {
    const w = win ? `&from=${win.from}&to=${win.to}` : ''
    return api<ServerMapResponse>(`/tasks/${taskId}/service-servermap/?service=${encodeURIComponent(service)}&inbound=2&outbound=2${w}`)
  },
  serviceMetrics: (taskId: number, service: string, win?: { from: number; to: number }): Promise<PrometheusMetricsResponse> => {
    const w = win ? `&from=${win.from}&to=${win.to}` : ''
    return api<PrometheusMetricsResponse>(`/tasks/${taskId}/service-metrics/?service=${encodeURIComponent(service)}${w}`)
  },
}

// ─── Runs API ──────────────────────────────────────────────────────────
// 按 run_id 操作单个 run（cancel / 实时指标 / 日志 / 报告 iframe）。
export const runsApi = {
  get: (runId: string) => api<TaskRun>(`/runs/${runId}/`),
  cancel: (runId: string) =>
    api<TaskRun>(`/runs/${runId}/cancel/`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  // 历史列表：勾选「保留」(keep) → run 目录不被自动清理；星标「历史基准」(每 task 单选)
  setKeep: (runId: string, keep: boolean) =>
    api<TaskRun>(`/runs/${runId}/set-keep/`, {
      method: 'POST',
      body: JSON.stringify({ keep }),
    }),
  setBaseline: (runId: string, isBaseline: boolean) =>
    api<TaskRun>(`/runs/${runId}/set-baseline/`, {
      method: 'POST',
      body: JSON.stringify({ is_baseline: isBaseline }),
    }),
  metrics: (runId: string, since?: string) => {
    const qs = since ? `?since=${encodeURIComponent(since)}` : ''
    return api<RunMetrics>(`/runs/${runId}/metrics/${qs}`)
  },
  log: (runId: string, tail = 200) =>
    api<{ lines: string[] }>(`/runs/${runId}/log/?tail=${tail}`),
  jtlUrl: (runId: string) => `/api/performance/runs/${runId}/jtl/`,
  reportUrl: (runId: string) => `/api/performance/runs/${runId}/report/`,
  // 报告按需生成:跑压测不再自动出 -e -o 报告,用户点"生成报告"才跑 jmeter -g,
  // 成功后删 results.jtl 腾盘(显示/分析走 DB,不依赖原始文件)。
  reportStatus: (runId: string): Promise<{ state: 'none' | 'ready'; has_jtl: boolean }> =>
    api(`/runs/${runId}/report-status/`),
  generateReport: (runId: string): Promise<{ state: 'ready'; has_jtl: boolean }> =>
    api(`/runs/${runId}/generate-report/`, { method: 'POST' }),
  // Step 3 接口级统计 + 错误明细（v1.2 起接真端点，mock 已删）
  samplerStats: (runId: string): Promise<SamplerStat[]> =>
    api<SamplerStat[]>(`/runs/${runId}/sampler-stats/`),
  errorSamples: (runId: string, q: ErrorSamplesQuery = {}): Promise<ErrorSamplesResponse> => {
    const params = new URLSearchParams()
    if (q.limit != null) params.set('limit', String(q.limit))
    if (q.sampler) params.set('sampler', q.sampler)
    if (q.codeBucket && q.codeBucket !== 'all') params.set('code_bucket', q.codeBucket)
    if (q.responseCode) params.set('response_code', q.responseCode)
    const qs = params.toString() ? `?${params.toString()}` : ''
    return api<ErrorSamplesResponse>(`/runs/${runId}/error-samples/${qs}`)
  },
  // 服端聚合：按 (code, label) 分组，count 是真实总数（不受 limit 影响）
  // ErrorMessageTable 用 —— sum 永远 = 真实总错误数
  errorAggregates: (runId: string, q: Omit<ErrorSamplesQuery, 'aggregate'> = {}): Promise<ErrorAggregatesResponse> => {
    const params = new URLSearchParams()
    params.set('aggregate', 'true')
    if (q.limit != null) params.set('limit', String(q.limit))
    if (q.sampler) params.set('sampler', q.sampler)
    if (q.codeBucket && q.codeBucket !== 'all') params.set('code_bucket', q.codeBucket)
    return api<ErrorAggregatesResponse>(`/runs/${runId}/error-samples/?${params.toString()}`)
  },
  // 按需拉单条错误样本的 response body（errors.xml 双轨）。错误明细表点击展开某行时调，
  // 后端早退式 iterparse 扫到首条匹配 (label, code) 即返回，避免全量扫大 errors.xml。
  // 聚合 / 明细列表端点为了避 502 不再内联 body，body 全走这个懒加载端点。
  responseBody: (runId: string, label: string, responseCode: string): Promise<{ body: string }> => {
    const params = new URLSearchParams()
    if (label) params.set('label', label)
    if (responseCode) params.set('response_code', responseCode)
    return api<{ body: string }>(`/runs/${runId}/response-body/?${params.toString()}`)
  },
  // 响应时间拆解：扫 JTL 算 Connect/Server/Receive 三段时序，前端按需拉一次
  // excludeKO=true 时只算 success=true 样本，看真实业务延迟
  latencyBreakdown: (runId: string, excludeKO = false): Promise<LatencyBreakdownResponse> => {
    const qs = excludeKO ? '?exclude_ko=true' : ''
    return api<LatencyBreakdownResponse>(`/runs/${runId}/latency-breakdown/${qs}`)
  },
  // 真实并发：扫 JTL allThreads/grpThreads 每秒峰值。并发数图实测实线用，跟计划虚线叠加。
  // 运行中 5s 轮询(JTL 周期增长)、终态 one-shot。
  concurrency: (runId: string): Promise<ConcurrencyResponse> =>
    api<ConcurrencyResponse>(`/runs/${runId}/concurrency/`),
  // § 11 Pinpoint 接入 v0：run 终态拉到的慢 trace 元数据；run 还在跑 / Pinpoint
  // 未启用 / 无数据时返回空数组
  pinpointTraces: (runId: string): Promise<PinpointTrace[]> =>
    api<PinpointTrace[]>(`/runs/${runId}/pinpoint-traces/`),
  // serverMap 服务拓扑（按 run 时段从 Pinpoint 拉）；opts.service 单服务、inbound/outbound
  // 上下游展开跳数（服务诊断页用深度2）。Pinpoint 未启用/不可达 → enabled=false 或空。
  pinpointServerMap: (
    runId: string,
    opts?: { service?: string; inbound?: number; outbound?: number; from?: number; to?: number },
  ): Promise<ServerMapResponse> => {
    const qs = new URLSearchParams()
    if (opts?.service) qs.set('service', opts.service)
    if (opts?.inbound != null) qs.set('inbound', String(opts.inbound))
    if (opts?.outbound != null) qs.set('outbound', String(opts.outbound))
    if (opts?.from != null && opts?.to != null) { qs.set('from', String(opts.from)); qs.set('to', String(opts.to)) }
    const q = qs.toString()
    return api<ServerMapResponse>(`/runs/${runId}/pinpoint-servermap/${q ? `?${q}` : ''}`)
  },
  // 单服务诊断聚合（事务/异常/慢URL/活跃线程/连接池/agent）；brief=只查事务概览(汇总行用)
  // win 非空 → 用指定时间窗（前端「近 N 分/时」预设），否则用 run 窗口
  pinpointDiagnosis: (runId: string, service: string, brief = false, win?: { from: number; to: number }): Promise<DiagnosisResponse> => {
    const w = win ? `&from=${win.from}&to=${win.to}` : ''
    return api<DiagnosisResponse>(`/runs/${runId}/pinpoint-diagnosis/?service=${encodeURIComponent(service)}${brief ? '&brief=1' : ''}${w}`)
  },
  // 某服务 run 窗口的 Pod 时序（Prometheus）。终态读 DB 快照秒开；前端「本次压测」用它
  serviceMetrics: (runId: string, service: string): Promise<PrometheusMetricsResponse> =>
    api<PrometheusMetricsResponse>(`/runs/${runId}/service-metrics/?service=${encodeURIComponent(service)}`),
  // Arthas 诊断输出留存（Step 3 → Step 4）
  arthasCaptures: (runId: string, service?: string): Promise<ArthasCapture[]> =>
    api<ArthasCapture[]>(`/runs/${runId}/arthas-captures/${service ? `?service=${encodeURIComponent(service)}` : ''}`),
  saveArthasCapture: (runId: string, body: { service?: string; pod?: string; command: string; output: string; note?: string }): Promise<ArthasCapture> =>
    api<ArthasCapture>(`/runs/${runId}/arthas-captures/`, { method: 'POST', body: JSON.stringify(body) }),
  deleteArthasCapture: (runId: string, id: number): Promise<void> =>
    api<void>(`/runs/${runId}/arthas-captures/delete/`, { method: 'POST', body: JSON.stringify({ id }) }),
  // zapp-server 实时列 集群/命名空间/某服务的 pod（Arthas 终端级联选，免手填）
  arthasClusters: (): Promise<{ id: number; name: string }[]> => api(`/arthas/clusters/`),
  arthasNamespaces: (cluster: number | string): Promise<string[]> => api(`/arthas/namespaces/?cluster=${cluster}`),
  arthasPods: (cluster: number | string, namespace: string, service: string): Promise<{ pod: string; namespace: string; containers: string[] }[]> =>
    api(`/arthas/pods/?cluster=${cluster}&namespace=${encodeURIComponent(namespace)}&service=${encodeURIComponent(service)}`),
  // § 12 S1：run 期间关键事件锚点（ramp_done / hold_start / shutdown_start /
  // first_error / error_rate_breached / p99_sla_breached）；前端时间轴 markLine 用
  events: (runId: string): Promise<RunEvent[]> =>
    api<RunEvent[]>(`/runs/${runId}/events/`),

  // 软删 TaskRun + 物理清 run_dir + InfluxDB DELETE。表行保留供大盘统计。
  // 活跃 run（pre_checking/pending/running/cancelling）后端 409 拒绝。
  delete: (runId: string): Promise<void> =>
    api<void>(`/runs/${runId}/`, { method: 'DELETE' }),
}

// ─── LoadGenerators API（v1.2 容器化压力源） ────────────────────────────
// 前端只读列出在线 agent + scaleUp/Down 触发编排；register/heartbeat 是 agent 内部用
export interface SystemMetrics {
  cpu_pct: number
  mem_pct: number
  mem_used_gb: number
  mem_total_gb: number
  net_kbs_in: number
  net_kbs_out: number
  disk_iops_read: number
  disk_iops_write: number
  timestamp: number
}

export const servicesApi = {
  /** G2：被压测服务列表（v1.3 Grafana 接入 v0）。后端 Service 表，不分页 */
  list: () => api<Service[]>('/services/'),
}

export const loadGeneratorsApi = {
  list: () => api<LoadGenerator[]>('/load-generators/'),
  get: (id: number) => api<LoadGenerator>(`/load-generators/${id}/`),
  scaleUp: (count: number) =>
    api<{ new_pods: string[]; count: number }>('/load-generators/scale-up/', {
      method: 'POST',
      body: JSON.stringify({ count }),
    }),
  scaleDown: (opts: { pod_names?: string[]; idle_only?: boolean }) =>
    api<{ removed: string[] }>('/load-generators/scale-down/', {
      method: 'POST',
      body: JSON.stringify(opts),
    }),
  systemMetrics: (id: number) =>
    api<SystemMetrics>(`/load-generators/${id}/system-metrics/`),
}

// ─── Prometheus 数据源 API ──────────────────────────────────────────
export const prometheusSourcesApi = {
  /** 数据源列表（Step 2 下拉框用） */
  list: () => api<PrometheusDataSource[]>('/prometheus-sources/'),
  /** 从指定数据源拉 job 列表（Step 2 服务多选） */
  services: (sourceId: number, search?: string) => {
    const qs = search ? `?search=${encodeURIComponent(search)}` : ''
    return api<PrometheusServiceList>(`/prometheus-sources/${sourceId}/services/${qs}`)
  },
  /** 查询指定服务的监控指标时序（Step 3 面板） */
  metrics: (sourceId: number, opts: {
    service: string
    start: string | number
    end: string | number
    step?: string
    metrics?: string
  }) => {
    const params = new URLSearchParams()
    params.set('service', opts.service)
    params.set('start', String(opts.start))
    params.set('end', String(opts.end))
    if (opts.step) params.set('step', opts.step)
    if (opts.metrics) params.set('metrics', opts.metrics)
    return api<PrometheusMetricsResponse>(`/prometheus-sources/${sourceId}/metrics/?${params}`)
  },
  /** 查询 fluent-bit 实时监控数据（所有 enabled 数据源汇总）
   * @param time 可选，Unix 时间戳，用于查询历史时刻的数据
   */
  fluentBit: (time?: number) =>
    api<FluentBitMetricsResponse>('/prometheus-sources/fluent-bit/' + (time ? `?time=${time}` : '')),
}

