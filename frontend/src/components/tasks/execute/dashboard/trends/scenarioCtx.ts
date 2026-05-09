/**
 * 场景驱动焦点图的单一推断入口。
 *
 * task.thread_groups_config 只存 enabled TG（禁用的 TG 在 PATCH body 里缺席），
 * 所以"主场景"直接取数组第一项；多 TG 不一致时 KpiBar 会挂 +N 提示。
 *
 * 老数据缺 scenario 字段 → inferScenarioFromKind(kind) 兜底；
 * 都缺或 task null → 返回 null，外层 fallback 到通用趋势带。
 */
import {
  SCENARIOS, scenarioById, inferScenarioFromKind,
  type ScenarioDef,
} from '@/components/tasks/configStageCtx'
import type { Task, ThreadGroupConfig } from '@/types/task'

export function pickPrimaryScenario(task: Task | null): ScenarioDef | null {
  if (!task) return null
  const cfgs = task.thread_groups_config
  if (!cfgs || !cfgs.length) return null
  const first = cfgs[0]
  const id = first.scenario ?? inferScenarioFromKind(first.kind)
  return scenarioById(id)
}

/** 多 TG 时，主场景之外还有几个 enabled TG（KpiBar 徽章用 "+N" 标） */
export function extraScenarioCount(task: Task | null): number {
  if (!task) return 0
  return Math.max(0, (task.thread_groups_config?.length ?? 0) - 1)
}

/** 多 TG 时罗列每个 TG 的场景定义（hover tooltip 用） */
export function listScenarios(task: Task | null): ScenarioDef[] {
  if (!task) return []
  return (task.thread_groups_config || []).map((c: ThreadGroupConfig) => {
    const id = c.scenario ?? inferScenarioFromKind(c.kind)
    return scenarioById(id)
  })
}

// 重导出，避免上层多处 import 配 ctx 文件
export { SCENARIOS, scenarioById, inferScenarioFromKind }
export type { ScenarioDef }
