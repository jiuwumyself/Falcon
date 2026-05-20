import type {
  Environment, ErrorAggregatesResponse, ErrorSamplesQuery, ErrorSamplesResponse,
  LatencyBreakdownResponse, LoadGenerator, Paginated, PinpointTrace, PrometheusDataSource,
  PrometheusMetricsResponse, PrometheusServiceList, RunEvent,
  RunMetrics, SamplerStat, Service, Task, TaskRun,
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
  metrics: (runId: string, since?: string) => {
    const qs = since ? `?since=${encodeURIComponent(since)}` : ''
    return api<RunMetrics>(`/runs/${runId}/metrics/${qs}`)
  },
  log: (runId: string, tail = 200) =>
    api<{ lines: string[] }>(`/runs/${runId}/log/?tail=${tail}`),
  jtlUrl: (runId: string) => `/api/performance/runs/${runId}/jtl/`,
  reportUrl: (runId: string) => `/api/performance/runs/${runId}/report/`,
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
  // 响应时间拆解：扫 JTL 算 Connect/Server/Receive 三段时序，前端按需拉一次
  // excludeKO=true 时只算 success=true 样本，看真实业务延迟
  latencyBreakdown: (runId: string, excludeKO = false): Promise<LatencyBreakdownResponse> => {
    const qs = excludeKO ? '?exclude_ko=true' : ''
    return api<LatencyBreakdownResponse>(`/runs/${runId}/latency-breakdown/${qs}`)
  },
  // § 11 Pinpoint 接入 v0：run 终态拉到的慢 trace 元数据；run 还在跑 / Pinpoint
  // 未启用 / 无数据时返回空数组
  pinpointTraces: (runId: string): Promise<PinpointTrace[]> =>
    api<PinpointTrace[]>(`/runs/${runId}/pinpoint-traces/`),
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
    job: string
    start: string | number
    end: string | number
    step?: string
    metrics?: string
  }) => {
    const params = new URLSearchParams()
    params.set('job', opts.job)
    params.set('start', String(opts.start))
    params.set('end', String(opts.end))
    if (opts.step) params.set('step', opts.step)
    if (opts.metrics) params.set('metrics', opts.metrics)
    return api<PrometheusMetricsResponse>(`/prometheus-sources/${sourceId}/metrics/?${params}`)
  },
}

