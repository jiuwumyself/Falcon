export type BizCategory = 'shared' | 'ai' | 'kg' | 'custom'

export type RunStatus = 'pending' | 'running' | 'success' | 'fail' | 'cancelled'

// 任务在 wizard 流程中的展示态：v1 只有 draft / configured 两态，
// v1.1 接执行模块后会再加 running / success / failed
export type TaskStatus = 'draft' | 'configured' | 'running' | 'success' | 'failed'

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
  csv_bindings: TaskCsvBinding[]
  status: TaskStatus
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

export interface UltimateTGParams {
  users: number
  initial_delay: number
  ramp_up: number
  hold: number
  shutdown: number
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
  params: Record<string, number | string>
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
  error_message: string
}

export interface Paginated<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
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
