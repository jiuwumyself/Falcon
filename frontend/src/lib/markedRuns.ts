// 「进数据分析」标记的纯前端 localStorage 实现。
// v1.3 数据分析功能落地时换成后端字段（TaskRun.marked_for_analysis），接口形态不变。
//
// key 形如 `marked_runs:42`（绑 task_id），value 是 run_id 数组的 JSON 字符串。

const KEY_PREFIX = 'marked_runs:'

function storageKey(taskId: number): string {
  return `${KEY_PREFIX}${taskId}`
}

export function getMarked(taskId: number): Set<string> {
  try {
    const raw = localStorage.getItem(storageKey(taskId))
    if (!raw) return new Set()
    const arr = JSON.parse(raw)
    return Array.isArray(arr) ? new Set(arr as string[]) : new Set()
  } catch {
    return new Set()
  }
}

export function toggleMarked(taskId: number, runId: string): Set<string> {
  const set = getMarked(taskId)
  if (set.has(runId)) set.delete(runId)
  else set.add(runId)
  try {
    localStorage.setItem(storageKey(taskId), JSON.stringify([...set]))
  } catch {
    // quota exceeded / disabled → 静默，UI 仍能用（刷新后丢）
  }
  return new Set(set)
}

export function removeMarked(taskId: number, runId: string): void {
  const set = getMarked(taskId)
  if (!set.has(runId)) return
  set.delete(runId)
  try {
    localStorage.setItem(storageKey(taskId), JSON.stringify([...set]))
  } catch {
    // ignore
  }
}
