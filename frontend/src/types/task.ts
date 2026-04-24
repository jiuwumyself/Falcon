export type BizCategory = 'shared' | 'ai' | 'kg'

export type RunStatus = 'pending' | 'running' | 'success' | 'fail' | 'cancelled'

export interface Task {
  id: number
  title: string
  description: string
  biz_category: BizCategory
  jmx_filename: string          // bare filename under <JMETER_HOME>/scripts/
  jmx_hash: string
  csv_filename: string          // bare CSV filename (empty if none); same scripts/ dir
  virtual_users: number
  ramp_up_seconds: number
  duration_seconds: number
  run_jmx_filename: string      // Step 2 派生可执行脚本文件名（空串 = 未配置）
  thread_groups_config: ThreadGroupConfig[]
  environment: number | null    // Environment id or null
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

export type ComponentDetail = HttpSamplerDetail | HeaderManagerDetail
