/**
 * 错误展示的共用元数据 —— 合并「接口统计 + 错误明细」后，donut（错误构成桶）
 * 和接口展开行（code + message）都从这里取，避免逻辑分散在多个组件里漂移。
 */
import { SEMANTIC } from './semanticColors'
import type { ErrorAggregateRow } from '@/types/task'

/**
 * 失败原因 5 类分桶（key 对齐后端 RunAnalysis.error_breakdown / TaskRun.error_breakdown）。
 * 颜色：4xx/5xx/assertion/connect 复用 SEMANTIC 语义色，timeout 用 cyan、other 用 gray。
 */
// short = 图例紧凑标签（突出错误代码/类型，避免窄卡片里被截断）；label = 完整描述（tooltip 用）
export const BUCKET_META: Record<string, { short: string; label: string; color: string; desc: string }> = {
  '4xx': { short: '4xx', label: '4xx 业务异常', color: SEMANTIC.latency, desc: '客户端业务校验失败（401/403/404/422 等）' },
  '5xx': { short: '5xx', label: '5xx 服务端错误', color: SEMANTIC.errors, desc: '服务端崩溃 / 异常（500/502/503/504 等）' },
  assertion: { short: '断言', label: '断言失败', color: SEMANTIC.saturation, desc: 'JMeter Assertion 失败（业务字段校验未通过）' },
  timeout: { short: '超时', label: '超时', color: '#06b6d4', desc: '读超时 / 连接超时（服务不响应或网络慢）' },
  connect_error: { short: '连接错误', label: '连接错误', color: SEMANTIC.traffic, desc: '连接被拒 / 域名解析失败 / 网络不可达' },
  other: { short: '其他', label: '其他', color: '#9ca3af', desc: '未匹配规则的错误（请检查 jmeter.log）' },
}

export function bucketMeta(key: string) {
  return BUCKET_META[key] ?? BUCKET_META.other
}

/** HTTP 标准 reason phrase（HTTP/2 服务下 responseMessage 字段为空，按 code 派生）。 */
export const HTTP_REASON: Record<string, string> = {
  '400': 'Bad Request',
  '401': 'Unauthorized',
  '403': 'Forbidden',
  '404': 'Not Found',
  '405': 'Method Not Allowed',
  '408': 'Request Timeout',
  '409': 'Conflict',
  '413': 'Payload Too Large',
  '415': 'Unsupported Media Type',
  '422': 'Unprocessable Entity',
  '429': 'Too Many Requests',
  '500': 'Internal Server Error',
  '501': 'Not Implemented',
  '502': 'Bad Gateway',
  '503': 'Service Unavailable',
  '504': 'Gateway Timeout',
}

/** 从完整 URL 抽 path 部分（去掉协议 + 域名）；非合法 URL 兜底取末段。 */
export function urlPath(url: string): string {
  if (!url) return ''
  try {
    return new URL(url).pathname
  } catch {
    const i = url.indexOf('://')
    if (i < 0) return url
    const j = url.indexOf('/', i + 3)
    return j < 0 ? '' : url.slice(j)
  }
}

/**
 * 一条错误聚合行的展示文案：responseMessage / failureMessage 优先；
 * 空时按 HTTP_REASON[code] · path 派生（HTTP/2 服务下 responseMessage 必空）。
 */
export function errorMessageOf(r: ErrorAggregateRow): string {
  const real = (r.sample_failure_message || r.sample_message || '').trim()
  if (real) return real
  const code = (r.response_code || '').trim()
  const path = urlPath((r.sample_url || '').trim())
  const reason = HTTP_REASON[code]
  if (reason && path) return `${reason} · ${path}`
  if (reason) return reason
  if (path) return path
  return r.label || '(no message)'
}
