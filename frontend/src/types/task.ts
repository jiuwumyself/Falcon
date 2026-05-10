export type BizCategory = 'shared' | 'ai' | 'kg' | 'custom'

// Step 3 起 RunStatus 跟后端枚举完全对齐（fail 改名 failed，新增 4 个）
export type RunStatus =
  | 'pre_checking'
  | 'pre_check_failed'
  | 'pending'
  | 'running'
  | 'cancelling'
  | 'success'
  | 'failed'
  | 'timeout'
  | 'cancelled'

// 任务在列表 / wizard 中的展示态：未跑过时 draft/configured，
// 跑过则直接展示最近 run 的 status（同 RunStatus 枚举）
export type TaskStatus = 'draft' | 'configured' | RunStatus

export interface TaskCsvBinding {
  component_path: string  // 索引路径，对齐组件树的 path（如 "0.0.3"）
  filename: string        // scripts/ 下的 bare 文件名
}

export interface Task {
  id: number
  title: string
  description: string
  biz_category: BizCategory
  jmx_filename: string          // bare filename under <JMETER_HOME>/scripts/
  jmx_hash: string
  virtual_users: number
  ramp_up_seconds: number
  duration_seconds: number
  thread_groups_config: ThreadGroupConfig[]
  environment: number | null    // Environment id or null
  service_names: string[]       // Step 2 选的"被压测服务"名列表（v1.2，前端 mock；多选）
  csv_bindings: TaskCsvBinding[]
  status: TaskStatus
  active_run_id: string | null  // 后端 Step 3 加：有活跃 run 时直接给前端 run_id
  owner: number | null
  created_at: string
  updated_at: string
}

export interface Environment {
  id: number
  name: string
  description: string
  is_default: boolean
  host_entries: { hostname: string; ip: string }[]
  created_at: string
  updated_at: string
}

// ─── Step 2 被压测服务（v1.2，服务库目前是前端 mock，v1.3 接后端表）───
// v1.3：jvm 加进来，对应 RunDashboard 的 JVM tab（heap/GC/thread iframe）
export type GrafanaPanelType = 'service' | 'trace' | 'jvm'

export interface GrafanaPanel {
  name: string                // 按钮上展示的名字
  url: string                 // iframe src，前端会拼 ?from=...&to=... 时间窗
  type: GrafanaPanelType      // service = 服务情况；trace = 链路情况
}

export interface Service {
  id: number                  // 后端 Service 表 PK（v1.3 起 mock 改为真表）
  name: string                // 用户可见的服务名，task.service_names 里存的就是 name
  base_url: string            // 服务对外地址（仅展示用）
  grafana_url: string         // 服务对应的 Grafana 仪表板根 URL（兜底，没配 panels 时用）
  pinpoint_app: string        // Pinpoint application name（v1.3 接入用）
  arthus_endpoint: string     // Arthus 服务端 endpoint（v1.5+ 接入用）
  description: string
  grafana_panels: GrafanaPanel[]   // Step 3 RuntimeStatusPanel + JVM tab 按 type 分配
  created_at?: string
  updated_at?: string
}

// 占位：v1.2 LoadGenerator 容器化压力源（Phase A2 实现）
export type LoadGeneratorStatus = 'pending' | 'idle' | 'busy' | 'lost'

export interface LoadGenerator {
  id: number
  pod_name: string
  hostname: string
  ip: string
  port: number
  status: LoadGeneratorStatus
  cpu_cores: number
  memory_gb: number
  max_vusers: number
  orchestrator_type: 'k8s' | 'docker' | string
  registered_at: string
  last_heartbeat_at: string | null
  released_at: string | null
}

// ─── Step 2 线程组配置 ────────────────────────────────────────────────

export type TGKind =
  | 'ThreadGroup'
  | 'SteppingThreadGroup'
  | 'ConcurrencyThreadGroup'
  | 'UltimateThreadGroup'
  | 'ArrivalsThreadGroup'

export type ScenarioId = 'baseline' | 'load' | 'stress' | 'soak' | 'spike' | 'throughput'

export interface StandardTGParams {
  users: number
  ramp_up: number
  duration: number
}

export interface SteppingTGParams {
  initial_threads: number
  step_users: number
  step_delay: number
  step_count: number
  hold: number
  shutdown: number
}

export interface ConcurrencyTGParams {
  target_concurrency: number
  ramp_up: number
  steps: number
  hold: number
  unit: 'S' | 'M'
}

export interface UltimatePeakRow {
  users: number
  initial_delay: number
  ramp_up: number
  hold: number
  shutdown: number
}

export interface UltimateTGParams {
  rows: UltimatePeakRow[]
}

export interface ArrivalsTGParams {
  target_rps: number
  ramp_up: number
  steps: number
  hold: number
  unit: 'S' | 'M'
}

export type TGParams =
  | StandardTGParams | SteppingTGParams | ConcurrencyTGParams
  | UltimateTGParams | ArrivalsTGParams

// 某个 ThreadGroup 在 JMX 里的当前状态（GET /thread-groups/ 每项返回）
export interface ThreadGroupInfo {
  path: string
  kind: TGKind
  tag: string         // 原始 JMX tag, like "kg.apc.jmeter.threads.SteppingThreadGroup"
  testname: string
  enabled: boolean
  current_params: Record<string, number | string>
}

// 前端要发回去的配置（PATCH body 里）
export interface ThreadGroupConfig {
  path: string
  scenario?: ScenarioId   // UI 语义标识，后端直通存盘
  kind: TGKind
  params: Record<string, any>
}

export interface ThreadGroupsResponse {
  thread_groups: ThreadGroupInfo[]
  saved_config: ThreadGroupConfig[]
  environment: number | null
}

export interface ValidateResult {
  path: string
  testname: string
  url: string
  status: number
  elapsed_ms: number
  ok: boolean
  error?: string
  unresolved_vars?: string[]
  warnings?: string[]
  // 仅 XML JTL 模式有值（试跑期间 save_response_data=true）
  response_body?: string
  response_headers?: string
  request_data?: string
  response_message?: string
  assertion_failures?: string[]
}

// 本次试跑实际执行的 TG（仅 enabled=true 的），用户能看出禁用 TG 没参与
export interface ExecutedTg {
  path: string
  kind: string
  testname: string
}

// 试跑响应：任务级 warnings（DNS 注入跳过等）+ 每接口结果 + 实际跑的 TG
export interface ValidateResponse {
  warnings: string[]
  results: ValidateResult[]
  executed_tgs: ExecutedTg[]
}

export interface TaskRun {
  id: number
  run_id: string                // Step 3 起：面向用户的短 uuid，URL / 目录名 / InfluxDB tag 都用它
  task: number
  status: RunStatus
  started_at: string | null
  finished_at: string | null
  virtual_users: number
  ramp_up_seconds: number
  duration_seconds: number
  total_requests: number
  avg_rps: number
  p99_ms: number
  error_rate: number
  // § 12 S2 失败原因 5 类分桶（终态时填，运行中为空 dict）
  // 桶 key：'4xx' / '5xx' / 'assertion' / 'timeout' / 'connect_error' / 'other'
  error_breakdown?: Record<string, number>
  error_message: string
  // Step 3 子进程编排相关
  pre_check_log: string
  pid: number | null
  stop_port: number | null
  last_heartbeat_at: string | null
  cancel_requested_at: string | null
  archived_at: string | null
}

// § 12 S1 关键事件锚点：run 期间的状态切换 / 阈值破坏事件，前端时间轴 markLine 用
export type RunEventType =
  | 'ramp_done'
  | 'hold_start'
  | 'shutdown_start'
  | 'first_error'
  | 'error_rate_breached'
  | 'p99_sla_breached'

export interface RunEvent {
  id: number
  event_type: RunEventType
  ts_ms: number          // 毫秒 epoch
  metadata: Record<string, any>
  created_at: string
}

// § 11 Pinpoint 接入 v0：run 终态拉到的慢 trace 元数据列表
export interface PinpointTrace {
  id: number
  service_name: string
  trace_id: string
  elapsed_ms: number
  start_ts_ms: number
  exception_type: string         // 无异常时空串
  pinpoint_detail_url: string    // 点击跳到 Pinpoint 原生 transactionView 页面
  created_at: string
}

// Step 3 实时指标 / 归档查询返回结构（GET /runs/:run_id/metrics?since=...）
export type SeriesPoint = [number, number]   // [ms_epoch, value]

export interface RunMetricsSeries {
  rps: SeriesPoint[]
  p50_ms: SeriesPoint[]
  p95_ms: SeriesPoint[]
  p99_ms: SeriesPoint[]
  // P0 #2：OK / KO 拆双轨。overall p99 含 KO 样本（401/403 快速返回拉低真实业务
  // 延迟分布），AI 分析时要看 OK 单独的分位数；KO 单独看判断"是快速失败还是慢超时"。
  // 单 host 单 sample 都是 success=true 时 p99_ok_ms === p99_ms。
  // by_tg / by_host 切片暂不拆 OK/KO（query 数据量翻倍，先在 overall 上线）。
  p50_ok_ms?: SeriesPoint[]
  p95_ok_ms?: SeriesPoint[]
  p99_ok_ms?: SeriesPoint[]
  p50_ko_ms?: SeriesPoint[]
  p95_ko_ms?: SeriesPoint[]
  p99_ko_ms?: SeriesPoint[]
  error_rate: SeriesPoint[]
  error_count: SeriesPoint[]   // 每秒失败数（总错误曲线 + by_tg 错误明细用）
  bytes_recv: SeriesPoint[]    // 每秒接收字节
  bytes_sent: SeriesPoint[]    // 每秒发送字节
  active_users: SeriesPoint[]
}

export interface RunMetricsTotals {
  total_count: number          // 整 run 累计请求数（ok + ko）
  total_errors: number         // 整 run 累计失败数
  total_bytes_recv: number     // 整 run 累计接收字节
  total_bytes_sent: number     // 整 run 累计发送字节
}

export interface RunMetrics {
  overall: RunMetricsSeries
  by_tg: Record<string, RunMetricsSeries>   // key = JMeter sample label / TG name
  by_host: Record<string, RunMetricsSeries> // v1.2：key = agent pod_name；单机时只有 1 个 key
  totals: RunMetricsTotals                  // 累计 KPI（KpiBar 用）
  last_ts: string                           // 下次轮询的 since 参数
  run: TaskRun                              // 后端附带最新 run 状态
}

export interface Paginated<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

// ─── Step 3 接口级统计 + 错误明细 ───────────────────────────────────
// 后端来源：sampler_stats 解析 JMeter HTML 报告里的 statistics.json；
// errors 流式扫 JTL CSV success=false 的行。前端先用 mock 渲染。

export interface SamplerStat {
  label: string
  total: number
  success: number
  error: number
  avg_ms: number
  min_ms: number
  max_ms: number
  p50_ms: number
  p90_ms: number
  p99_ms: number
  avg_rps: number
  avg_bytes: number
  top_errors: { reason: string; count: number }[]
}

export type SamplerSortKey = 'error_rate_desc' | 'total_desc' | 'p99_desc'

export interface ErrorSample {
  timestamp: number       // ms epoch
  label: string
  method: string
  response_code: string   // '500' / 'Non HTTP response code: ...' / 'Assertion failed' 等
  response_message: string
  failure_message: string // 优先来源 = assertion msg
  url: string             // 完整请求 URL，需 -Jjmeter.save.saveservice.url=true
  elapsed_ms: number
  response_body: string   // 已截断 ≤ 1 KB
}

export type ErrorCodeBucket = 'all' | '4xx' | '5xx' | 'assertion' | 'timeout'

export interface ErrorSamplesResponse {
  samples: ErrorSample[]
  total: number
}

// aggregate=true 模式返回：按 (code, label) 服端聚合，count 是真实总数（不受 limit 影响）
// 用于 ErrorMessageTable —— sum 永远 = 真实总错误数
export interface ErrorAggregateRow {
  response_code: string
  label: string
  count: number
  sample_message: string         // 该组首次出现的 responseMessage
  sample_failure_message: string // 该组首次出现的 failureMessage
  sample_url: string             // 该组首次出现的 URL
}

export interface ErrorAggregatesResponse {
  aggregates: ErrorAggregateRow[]
  total: number
}

export interface ErrorSamplesQuery {
  limit?: number
  sampler?: string
  codeBucket?: ErrorCodeBucket
  aggregate?: boolean   // true → 走 ErrorAggregatesResponse 形状
}

// 响应时间拆解：扫 JTL 算 Connect / 服务端处理 / 客户端接收三段时序
// LatencyChart "拆解" mode 用 —— 看出 RT 高在哪一段
export interface LatencyBreakdownResponse {
  connect_ms: SeriesPoint[]   // TCP 握手时间
  server_ms: SeriesPoint[]    // 服务端处理时间（latency - connect）
  receive_ms: SeriesPoint[]   // 客户端接收时间（elapsed - latency）
}

export interface JmxComponent {
  path: string          // 索引路径，如 "0.0.1"
  tag: string           // JMX 元素标签，如 "HTTPSamplerProxy"
  testname: string      // GUI 里的组件名
  enabled: boolean
  kind: string          // 规范化类型（通常等于 tag；ConfigTestElement 按 guiclass 区分为 HttpDefaults）
  children: JmxComponent[]
}

// 可编辑组件的详细字段。按 `kind` 辨别不同 schema。
export interface HttpSamplerParam { name: string; value: string }
export interface HttpSamplerFile { path: string; paramname: string; mimetype: string }
export type HttpBodyMode = 'params' | 'raw'

export interface HttpSamplerDetail {
  kind: 'HTTPSamplerProxy'
  domain: string
  port: string
  protocol: string
  method: string
  path: string
  bodyMode: HttpBodyMode
  params: HttpSamplerParam[]
  body: string
  files: HttpSamplerFile[]
}

export interface HeaderManagerDetail {
  kind: 'HeaderManager'
  headers: { name: string; value: string }[]
}

export interface HttpDefaultsDetail {
  kind: 'HttpDefaults'
  domain: string
  port: string
  protocol: string
  path: string
  contentEncoding: string
  connectTimeout: string
  responseTimeout: string
  implementation: string
  followRedirects: boolean
  useKeepAlive: boolean
}

export interface JSONAssertionDetail {
  kind: 'JSONPathAssertion'
  jsonPath: string
  expectedValue: string
  jsonValidation: boolean
  expectNull: boolean
  invert: boolean
  isRegex: boolean
}

export interface BeanShellDetail {
  kind: 'BeanShellPostProcessor' | 'BeanShellPreProcessor'
  script: string
  parameters: string
  resetInterpreter: boolean
}

export interface RegexExtractorDetail {
  kind: 'RegexExtractor'
  refname: string
  regex: string
  template: string
  default: string
  matchNumber: string
  useHeaders: string
}

export interface JSONExtractorDetail {
  kind: 'JSONPathExtractor'
  varName: string
  jsonpath: string
  default: string
  matchNo: string
}

export interface CsvDataSetDetail {
  kind: 'CSVDataSet'
  variableNames: string
  delimiter: string
  fileEncoding: string
  ignoreFirstLine: boolean
  quotedData: boolean
  recycle: boolean
  stopThread: boolean
  shareMode: string
}

export type ComponentDetail =
  | HttpSamplerDetail
  | HeaderManagerDetail
  | HttpDefaultsDetail
  | JSONAssertionDetail
  | BeanShellDetail
  | RegexExtractorDetail
  | JSONExtractorDetail
  | CsvDataSetDetail
