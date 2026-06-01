import type { RunStatus } from '@/types/task'

// run 状态 → 标签 + 颜色。RunControlBar 状态徽章 + RunHistoryDropdown 行状态 chip 共用。
export const STATUS_META: Record<RunStatus, { label: string; color: string }> = {
  pre_checking: { label: '预检中', color: '#9ca3af' },
  pre_check_failed: { label: '预检失败', color: '#ef4444' },
  pending: { label: '排队中', color: '#9ca3af' },
  running: { label: '执行中', color: '#3b82f6' },
  cancelling: { label: '取消中', color: '#f59e0b' },
  success: { label: '成功', color: '#10b981' },
  failed: { label: '失败', color: '#ef4444' },
  timeout: { label: '超时', color: '#f59e0b' },
  cancelled: { label: '已取消', color: '#9ca3af' },
}
