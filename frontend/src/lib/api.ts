import type { Paginated, Task } from '@/types/task'

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
}
