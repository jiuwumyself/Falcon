/**
 * 性能测试指标的语义色字典 —— 跟 chartColors.ts 的"按 transaction hash 分色"互补。
 *
 * 业界约定（Datadog / Grafana / SignalFx 通用）：
 * - 错误（errors）→ 红：警告 / 异常
 * - 延迟（latency）→ 黄：性能下降信号
 * - 吞吐（traffic）→ 蓝：处理能力
 * - 饱和（saturation）→ 紫：资源占用 / 并发数
 * - 成功（success）→ 绿：正常态
 *
 * 用语义命名而不是颜色命名，让"颜色 = 指标含义"绑定，跨组件视觉一致。
 */

export const SEMANTIC = {
  errors: '#ef4444',     // red - 错误率 / 失败数 / 5xx
  latency: '#f59e0b',    // amber - 响应时间 / 4xx
  traffic: '#3b82f6',    // blue - RPS / 流量 / 2xx
  saturation: '#a855f7', // purple - 并发 VU / 资源占用
  success: '#10b981',    // emerald - 0 错误 / 全部通过
} as const

/**
 * 响应时间拆解三段（LatencyChart 拆解 mode 用）。
 * - connect：网络层（蓝，traffic 类）
 * - server：服务端处理（红，errors 类 —— 服务端是性能瓶颈最常见点）
 * - receive：数据接收（黄，latency 类 —— 受带宽 / 响应体大小影响）
 */
export const LATENCY_BREAKDOWN = {
  connect: SEMANTIC.traffic,
  server: SEMANTIC.errors,
  receive: SEMANTIC.latency,
} as const

/**
 * HTTP 状态码 → 颜色（4xx / 5xx / 2xx / assertion 等通用映射）。
 * ErrorMessageTable 的 codeColor 用。
 */
export function colorForHttpCode(code: string): string {
  const n = parseInt(code, 10)
  if (Number.isNaN(n)) return SEMANTIC.saturation  // assertion / Non HTTP
  if (n >= 500) return SEMANTIC.errors
  if (n >= 400) return SEMANTIC.latency
  return SEMANTIC.traffic
}

/**
 * 失败数 / 错误率 颜色策略：> 0 才染红，= 0 用主色（避免红/绿双饱和）。
 * KpiBar 用。
 */
export function colorForErrorMetric(
  v: number | null,
  primary: string,
  threshold = 0,
): string {
  if (v === null) return primary
  return v > threshold ? SEMANTIC.errors : primary
}

/**
 * 错误率三档（绿 / 黄 / 红），用于 ErrorRateGauge 数字着色。
 * 阈值跟 SLA 默认对齐：< 0.5% 优 / < 5% 警告 / >= 5% 严重
 */
export function colorForErrorRate(pct: number): string {
  if (pct < 0.5) return SEMANTIC.success
  if (pct < 5) return SEMANTIC.latency  // 黄色作"警告"
  return SEMANTIC.errors
}
