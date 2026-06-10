// 规则生成压测结论段落（纯函数，零后端依赖）。
// 把已有的指标 / 事件 / 诊断按模板拼成几句中文结论，供 Step 4 报告页「结论」区展示。
// 这是后续接真 LLM 的 prompt 雏形 + UI 槽位：将来用模型替换本函数即可，调用方不变。
import type { RunEvent, SamplerStat, TaskRun } from '@/types/task'

export interface ServiceFinding {
  service: string
  findings: { text: string; sev: 'high' | 'mid' }[]
}

export interface NarrativeInput {
  run: TaskRun
  samplers: SamplerStat[]
  events: RunEvent[]
  serviceFindings: ServiceFinding[]
  peakConcurrency: number | null
  peakRps: number | null         // 实测峰值 RPS（metrics.overall.rps 取 max），无则用 avg
  baselineP99: number | null     // 基线 run 的 all 行 P99，无基线则 null
}

const ERROR_BUCKET_CN: Record<string, string> = {
  '4xx': '4xx 客户端错误', '5xx': '5xx 服务端错误', assertion: '断言失败',
  timeout: '超时', connect_error: '连接错误', other: '其他错误',
}

function fmtMs(v: number): string {
  return v >= 1000 ? (v / 1000).toFixed(2) + 's' : Math.round(v) + 'ms'
}

export interface TgNarrativeInput {
  tgName: string
  scenarioLabel: string          // 场景中文名（基准/负载/压力…），无则空串
  errorRate: number              // 该 TG 错误率 %
  p99: number                    // 该 TG 峰值 P99 ms
  peakRps: number | null
  peakConcurrency: number | null
  totalRequests: number
  samplers: SamplerStat[]        // 该 TG 的接口统计
}

// 单个线程组(TG)的结论段落：混合压测里每个 TG 各出一份，定性各自健康度。
export function buildTgNarrative(i: TgNarrativeInput): string[] {
  const out: string[] = []
  const scn = i.scenarioLabel ? `${i.scenarioLabel}场景` : '该线程组'

  // 1) 容量 + 延迟
  {
    const parts: string[] = []
    if (i.peakConcurrency != null) parts.push(`峰值并发 ${i.peakConcurrency}`)
    if (i.peakRps != null) parts.push(`峰值吞吐 ${i.peakRps.toFixed(0)} req/s`)
    if (i.totalRequests) parts.push(`${i.totalRequests.toLocaleString()} 请求`)
    let s = `${scn}${parts.length ? '：' + parts.join('、') : ''}，P99 ${fmtMs(i.p99)}`
    const slow = [...i.samplers].filter((x) => x.label !== 'all').sort((a, b) => b.p99_ms - a.p99_ms)[0]
    if (slow && slow.p99_ms >= 1000) s += `；最慢接口「${slow.label}」${fmtMs(slow.p99_ms)}`
    out.push(s + '。')
  }

  // 2) 错误
  {
    if (i.errorRate < 0.5) {
      out.push('该线程组错误率处于健康区间，无明显失败。')
    } else {
      const worst = i.samplers.filter((x) => x.label !== 'all' && x.error > 0).sort((a, b) => b.error - a.error)[0]
      let s = `该线程组错误率 ${i.errorRate.toFixed(2)}%`
      if (worst) s += `，集中在「${worst.label}」（失败 ${worst.error} 次）`
      if (i.errorRate >= 5) s += '；该压力下已不可用，建议优先排查'
      out.push(s + '。')
    }
  }

  return out
}

// 生成结论段落数组，每条一句话；无数据的维度自动跳过。
export function buildNarrative(input: NarrativeInput): string[] {
  const { run, samplers, events, serviceFindings, peakConcurrency, peakRps, baselineP99 } = input
  const out: string[] = []
  const earlyAbort = events.some((e) => e.event_type === 'error_rate_breached')
  const er = run.error_rate ?? 0
  const p99 = run.p99_ms ?? 0

  // 1) 容量
  {
    const parts: string[] = []
    if (peakConcurrency != null) parts.push(`峰值并发 ${peakConcurrency}`)
    const rps = peakRps ?? run.avg_rps ?? 0
    if (rps > 0) parts.push(`峰值吞吐 ${rps.toFixed(0)} req/s`)
    if (run.total_requests) parts.push(`累计 ${run.total_requests.toLocaleString()} 请求`)
    if (parts.length) {
      let s = `本次压测 ${parts.join('、')}`
      if (earlyAbort) s += '，期间错误率突破阈值触发早停（实际承压能力低于计划负载）'
      out.push(s + '。')
    }
  }

  // 2) 延迟
  {
    let s = `整体 P99 延迟 ${fmtMs(p99)}`
    if (baselineP99 != null && baselineP99 > 0) {
      const d = ((p99 - baselineP99) / baselineP99) * 100
      if (d <= -3) s += `，较历史基线快 ${(-d).toFixed(0)}%（改善）`
      else if (d >= 3) s += `，较历史基线慢 ${d.toFixed(0)}%（退化，需关注）`
      else s += '，与历史基线基本持平'
    }
    out.push(s + '。')
  }

  // 3) 错误
  {
    if (er < 0.01 && !run.total_requests) {
      // 没数据不下结论
    } else if (er < 0.5) {
      out.push(`错误率 ${er.toFixed(2)}%，处于健康区间。`)
    } else {
      const bd = run.error_breakdown || {}
      const topBucket = Object.entries(bd).sort((a, b) => b[1] - a[1])[0]
      const worst = samplers.filter((s) => s.error > 0).sort((a, b) => b.error - a.error)[0]
      let s = `错误率 ${er.toFixed(2)}%`
      if (topBucket) s += `，主要为${ERROR_BUCKET_CN[topBucket[0]] || topBucket[0]}（${topBucket[1]} 次）`
      if (worst) s += `，集中在接口「${worst.label}」（失败 ${worst.error} 次）`
      out.push(s + '。')
    }
  }

  // 4) 瓶颈（每服务有 finding 才出句）
  {
    const withFindings = serviceFindings.filter((s) => s.findings.length)
    for (const sf of withFindings) {
      out.push(`服务「${sf.service}」检测到：${sf.findings.map((f) => f.text).join('、')}。`)
    }
    if (serviceFindings.length && !withFindings.length) {
      out.push('被压测服务侧未发现明显资源瓶颈（GC / 线程 / 慢接口 / 连接池均正常）。')
    }
  }

  // 5) 总体定性收尾
  {
    if (earlyAbort || er >= 5) {
      out.push('结论：服务在该压力下不可用或濒临崩溃，建议降低目标负载或先解决瓶颈后复测。')
    } else if (er >= 1) {
      out.push('结论：存在少量失败，建议复核失败接口与服务端日志后再判定是否达标。')
    } else {
      out.push('结论：服务在该压力下表现稳定，未见明显异常。')
    }
  }

  return out
}
