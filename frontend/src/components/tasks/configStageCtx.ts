import type { InjectionKey, Ref } from 'vue'
import { Activity, Gauge, TrendingUp, Clock, Zap, BarChart3 } from 'lucide-vue-next'
import type { ScenarioId, TGKind } from '@/types/task'

// v1 敲定的上限（与后端 services/jmx.py 的 MAX_USERS / MAX_DURATION_SECONDS 对齐）
export const MAX_USERS = 5000
export const MAX_DURATION_SECONDS = 43200  // 12 小时

// 6 个场景 → 底层 ThreadGroup + 推荐参数映射
// UI 只展示 label/desc/color/icon；kind + defaultParams 是选中该场景时自动套用的
export interface ScenarioDef {
  id: ScenarioId
  label: string
  desc: string
  color: string
  icon: any
  kind: TGKind
  // Ultimate 用 rows: UltimatePeakRow[] 嵌套；其余 kind 都是扁平 number/string 映射。
  defaultParams: Record<string, number | string | object>

  // 详细 tooltip：定义 / 典型参数范围 / 关注指标
  tooltip: {
    purpose: string
    typical: string
    focus: string
  }
}

export const SCENARIOS: ScenarioDef[] = [
  {
    id: 'baseline', label: '基准', color: '#3b82f6', icon: Activity,
    desc: '少量线程跑几分钟，建立 TPS 和 RT 基线。底层：标准 ThreadGroup。',
    kind: 'ThreadGroup',
    defaultParams: { users: 10, ramp_up: 5, duration: 300 },
    tooltip: {
      purpose: '单点性能基线测试。固定低并发跑足时长，输出"单台 / 单实例能扛多少"基础数据。',
      typical: '用户数 5-20，跑 5-15 分钟。',
      focus: 'P99 / RT 是否稳定，无明显抖动。',
    },
  },
  {
    id: 'load', label: '负载', color: '#10b981', icon: Gauge,
    desc: '阶梯式逐步加压，寻找系统性能拐点。底层：Stepping ThreadGroup。',
    kind: 'SteppingThreadGroup',
    defaultParams: {
      initial_threads: 0, step_users: 10, step_delay: 30,
      step_count: 10, hold: 60, shutdown: 5,
    },
    tooltip: {
      purpose: '阶梯式加压观察系统从空载到饱和全过程，找性能拐点。',
      typical: '每 30 秒加 10 人共 10 阶（最终 100 人），保持 1 分钟。',
      focus: 'RPS 增长拐点、错误率开始上升的临界值。',
    },
  },
  {
    id: 'stress', label: '压力', color: '#f59e0b', icon: TrendingUp,
    desc: '持续加压直至系统失败或明显劣化。底层：Stepping ThreadGroup。',
    kind: 'SteppingThreadGroup',
    defaultParams: {
      initial_threads: 50, step_users: 50, step_delay: 30,
      step_count: 10, hold: 60, shutdown: 5,
    },
    tooltip: {
      purpose: '起点已不低、继续阶梯加压，逼近系统极限。',
      typical: '从 50 人起步、每 30 秒加 50 人，跑到 500-1000 人。',
      focus: 'CPU / 内存 / GC 频率、错误暴增点、连接池耗尽。',
    },
  },
  {
    id: 'soak', label: '稳定性', color: '#8b5cf6', icon: Clock,
    desc: '动态维持恒定并发长时间跑，排查内存 / 连接池泄漏。底层：Concurrency ThreadGroup。',
    kind: 'ConcurrencyThreadGroup',
    defaultParams: { target_concurrency: 50, ramp_up: 60, steps: 5, hold: 3600, unit: 'S' },
    tooltip: {
      purpose: '中等并发恒定跑长时间，看是否泄漏 / 累积错误。',
      typical: '50-200 并发，跑 1-12 小时。',
      focus: 'RT / 错误率随时间漂移，内存 / 连接数是否单调增长。',
    },
  },
  {
    id: 'spike', label: '峰值', color: '#ef4444', icon: Zap,
    desc: '短时间瞬拉高用户再回落，模拟秒杀 / 直播开播等脉冲流量。底层：Ultimate ThreadGroup。',
    kind: 'UltimateThreadGroup',
    defaultParams: { rows: [{ users: 500, initial_delay: 0, ramp_up: 5, hold: 60, shutdown: 5 }] },
    tooltip: {
      purpose: '短时间冲到极高并发再回落，模拟秒杀 / 突发流量。',
      typical: '5 秒内冲到 500-2000 人，hold 60 秒，5 秒退出。',
      focus: '队列堆积情况、限流是否生效、回落后系统恢复时间。',
    },
  },
  {
    id: 'throughput', label: '吞吐量', color: '#ec4899', icon: BarChart3,
    desc: '按目标 RPS 施压，验证 SLA（如 2000 RPS 下 P99<200ms）。底层：Arrivals ThreadGroup。',
    kind: 'ArrivalsThreadGroup',
    defaultParams: { target_rps: 500, ramp_up: 60, steps: 10, hold: 600, unit: 'M' },
    tooltip: {
      purpose: '按 RPS 目标驱动（不按用户数），验证"系统能否撑住 N qps"。',
      typical: '目标 500-5000 RPS（每分钟），跑 10 分钟看尾延迟。',
      focus: 'success rate、tail latency（P95 / P99）、是否触发自动扩缩。',
    },
  },
]

export function scenarioById(id: ScenarioId): ScenarioDef {
  return SCENARIOS.find((s) => s.id === id) ?? SCENARIOS[1]  // fallback: load
}

// 已有保存配置但没有 scenario 字段时的兜底映射（best-effort）
export function inferScenarioFromKind(kind: TGKind): ScenarioId {
  switch (kind) {
    case 'ThreadGroup': return 'baseline'
    case 'SteppingThreadGroup': return 'load'
    case 'ConcurrencyThreadGroup': return 'soak'
    case 'UltimateThreadGroup': return 'spike'
    case 'ArrivalsThreadGroup': return 'throughput'
    default: return 'load'
  }
}

export interface ConfigStageCtx {
  isDark: Ref<boolean>
}

export const CONFIG_STAGE_CTX: InjectionKey<ConfigStageCtx> = Symbol('CONFIG_STAGE_CTX')
