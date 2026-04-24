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
  defaultParams: Record<string, number | string>
}

export const SCENARIOS: ScenarioDef[] = [
  {
    id: 'baseline', label: '基准', color: '#3b82f6', icon: Activity,
    desc: '少量线程跑几分钟，建立 TPS 和 RT 基线。底层：标准 ThreadGroup。',
    kind: 'ThreadGroup',
    defaultParams: { users: 10, ramp_up: 5, duration: 300 },
  },
  {
    id: 'load', label: '负载', color: '#10b981', icon: Gauge,
    desc: '阶梯式逐步加压，寻找系统性能拐点。底层：Stepping ThreadGroup。',
    kind: 'SteppingThreadGroup',
    defaultParams: {
      initial_threads: 0, step_users: 10, step_delay: 30,
      step_count: 10, hold: 60, shutdown: 5,
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
  },
  {
    id: 'soak', label: '稳定性', color: '#8b5cf6', icon: Clock,
    desc: '动态维持恒定并发长时间跑，排查内存 / 连接池泄漏。底层：Concurrency ThreadGroup。',
    kind: 'ConcurrencyThreadGroup',
    defaultParams: { target_concurrency: 50, ramp_up: 60, steps: 5, hold: 3600, unit: 'S' },
  },
  {
    id: 'spike', label: '峰值', color: '#ef4444', icon: Zap,
    desc: '短时间瞬拉高用户再回落，模拟秒杀 / 直播开播等脉冲流量。底层：Ultimate ThreadGroup。',
    kind: 'UltimateThreadGroup',
    defaultParams: { users: 500, initial_delay: 0, ramp_up: 5, hold: 60, shutdown: 5 },
  },
  {
    id: 'throughput', label: '吞吐量', color: '#ec4899', icon: BarChart3,
    desc: '按目标 RPS 施压，验证 SLA（如 2000 RPS 下 P99<200ms）。底层：Arrivals ThreadGroup。',
    kind: 'ArrivalsThreadGroup',
    defaultParams: { target_rps: 500, ramp_up: 60, steps: 10, hold: 600, unit: 'M' },
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
