/**
 * 给 transaction 名稳定哈希出颜色，刷新 / 重排序结果不变。
 * - 'all' 永远是绿色加粗（参考 Grafana 模板的 all 线）
 * - 其他 transaction 在调色板里轮转，hash 让同名 → 同色
 */

const PALETTE = [
  '#3b82f6', // blue
  '#f59e0b', // amber
  '#ef4444', // red
  '#a855f7', // purple
  '#06b6d4', // cyan
  '#ec4899', // pink
  '#14b8a6', // teal
  '#f97316', // orange
  '#6366f1', // indigo
  '#84cc16', // lime
  '#8b5cf6', // violet
  '#22d3ee', // sky
  '#fbbf24', // yellow
  '#fb7185', // rose
  '#10b981', // emerald
  '#a78bfa', // light purple
]

const ALL_COLOR = '#10b981'

function hash(str: string): number {
  let h = 0
  for (let i = 0; i < str.length; i++) {
    h = (h * 31 + str.charCodeAt(i)) | 0
  }
  return Math.abs(h)
}

export function colorFor(name: string): string {
  if (name === 'all' || name === '_overall') return ALL_COLOR
  return PALETTE[hash(name) % PALETTE.length]
}

export function widthFor(name: string): number {
  return name === 'all' || name === '_overall' ? 2.5 : 1.2
}

/** 半透明色（hex#RRGGBB → rgba(.., a)） */
export function withAlpha(hex: string, alpha: number): string {
  if (hex.length !== 7 || hex[0] !== '#') return hex
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r},${g},${b},${alpha})`
}

/**
 * 默认勾选的 transaction：取 RPS 累计前 N 名 + all。避免一上来就 20 条线糊在一起。
 */
export function pickDefaultSelected(
  txList: string[],
  rpsByTx: Record<string, number>,
  topN = 5,
): Record<string, boolean> {
  const sorted = [...txList].sort(
    (a, b) => (rpsByTx[b] || 0) - (rpsByTx[a] || 0),
  )
  const top = new Set(sorted.slice(0, topN))
  const selected: Record<string, boolean> = { all: true }
  for (const tx of txList) {
    selected[tx] = top.has(tx)
  }
  return selected
}
