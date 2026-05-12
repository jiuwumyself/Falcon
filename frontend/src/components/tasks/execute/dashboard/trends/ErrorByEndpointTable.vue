<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronDown, ChevronRight, FileJson, Info, Link2, MessageSquare, Tag } from 'lucide-vue-next'
import { runsApi } from '@/lib/api'
import type { ErrorAggregateRow, ErrorSample } from '@/types/task'
import { fmtInt } from './chartFactory'
import { colorForHttpCode, SEMANTIC } from './semanticColors'
import SampleList from './SampleList.vue'

// 「接口 + code + message」三键聚合表（替换原 ErrorTransactionTable + ErrorMessageTable）。
// 后端 errorAggregates endpoint key=(code, label, msg_norm)，每组真实 count。
// 前端按 count desc 排序；message 走 HTTP_REASON fallback；URL 进 hover tooltip。
//
// v1.3 起支持行展开：点行 → 拉该 (sampler, response_code) 的 ≤20 条样本 →
// 行下方滑出 SampleList（含时间戳 + body 二级展开），把"中→细"下钻做在同一个表里。

const props = defineProps<{
  rows: ErrorAggregateRow[]
  runId: string | null    // null 时表只读（不能点行展开）
  isDark: boolean
}>()

// primary 行的来源类型；body 不在这里——body 永远走 secondary 行（如有）。
type PrimarySource = 'message' | 'http_reason' | 'url' | 'label'

interface DisplayRow {
  label: string
  responseCode: string
  primary: string         // 第一行：responseMessage / failureMessage 优先，否则 HTTP_REASON 派生
  secondary: string       // 第二行：errors.xml 抓到的真实 response body；为空则不渲染
  primarySource: PrimarySource
  hasBody: boolean        // 图标用：拿到 body 时高亮 FileJson
  count: number
  url: string
}

// HTTP 标准 reason phrase（HTTP/2 服务下 responseMessage 字段为空，按 code 派生）
const HTTP_REASON: Record<string, string> = {
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

// 从完整 URL 抽 path 部分（去掉协议+域名）；非合法 URL 兜底取末段
function urlPath(url: string): string {
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

// 展开行状态：key = label|response_code（跟后端二键聚合同源）
const expandedKey = ref<string | null>(null)
const samplesCache = ref<Map<string, ErrorSample[]>>(new Map())
const samplesLoading = ref<Set<string>>(new Set())

function rowKey(r: { label: string; responseCode: string }): string {
  return `${r.label}|${r.responseCode}`
}

async function toggleRow(r: DisplayRow) {
  const key = rowKey(r)
  // 折叠
  if (expandedKey.value === key) {
    expandedKey.value = null
    return
  }
  expandedKey.value = key
  // 已缓存 / runId 缺失 → 不再拉
  if (samplesCache.value.has(key) || !props.runId) return
  // 首次展开拉样本：按 sampler + 精确 response_code 过滤；limit 20 个够看出模式
  samplesLoading.value.add(key)
  try {
    // limit 50：SampleList 按 (body, reason) dedup 后通常只剩几行，但要让
    // ×N 徽章接近真实数量需要多采几条。50 条扫 jtl 仍很快。聚合行的 count
    // 已经显示该组合**真实总数**（不受这里 limit 影响）。
    const res = await runsApi.errorSamples(props.runId, {
      sampler: r.label,
      responseCode: r.responseCode,
      limit: 50,
    })
    samplesCache.value.set(key, res.samples)
  } catch {
    // 失败也写入 cache，避免反复点反复拉；展示空态
    samplesCache.value.set(key, [])
  } finally {
    samplesLoading.value.delete(key)
  }
}

const displayRows = computed<DisplayRow[]>(() =>
  [...props.rows]
    .sort((a, b) => b.count - a.count)
    .map((r) => {
      const code = (r.response_code || '').trim() || '0'
      const url = (r.sample_url || '').trim()
      const path = urlPath(url)
      const body = (r.sample_response_body || '').trim()
      const real = (r.sample_failure_message || r.sample_message || '').trim()

      // primary（第一行）：responseMessage / failureMessage 优先；空时按 code / path 派生
      // HTTP/2 服务下 responseMessage 必空 → 自动走 http_reason 兜底
      let primary: string
      let primarySource: PrimarySource
      if (real) {
        primary = real
        primarySource = 'message'
      } else {
        const reason = HTTP_REASON[code]
        if (reason && path) {
          primary = `${reason} · ${path}`
          primarySource = 'http_reason'
        } else if (reason) {
          primary = reason
          primarySource = 'http_reason'
        } else if (path) {
          primary = path
          primarySource = 'url'
        } else if (url) {
          primary = url
          primarySource = 'url'
        } else {
          primary = r.label || '(no message)'
          primarySource = 'label'
        }
      }

      // secondary（第二行）：errors.xml 抓到的真实响应 body，截断 240 字；空则不渲染
      const secondary = body
        ? (body.length > 240 ? body.slice(0, 240) + '…' : body)
        : ''

      return {
        label: r.label || '(unknown)',
        responseCode: code,
        primary,
        secondary,
        primarySource,
        hasBody: !!secondary,
        count: r.count,
        url,
      }
    }),
)

const totalErrors = computed(() => displayRows.value.reduce((s, r) => s + r.count, 0))
const groupCount = computed(() => displayRows.value.length)

const headerColor = computed(() =>
  props.isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.5)',
)
const cellColor = computed(() =>
  props.isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.85)',
)
const subColor = computed(() =>
  props.isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)',
)
const dividerColor = computed(() =>
  props.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
)

const codeColor = colorForHttpCode

// 图标：拿到 body 时 FileJson 高亮（说明 errors.xml 双轨抓到真实响应）；
// 否则按 primary 来源走 fallback 链。
const PRIMARY_META: Record<PrimarySource, { icon: any; tooltip: string }> = {
  message: {
    icon: MessageSquare,
    tooltip: '服务端返回的 responseMessage / failureMessage',
  },
  http_reason: {
    icon: Info,
    tooltip: 'HTTP 标准描述（HTTP/2 服务下 responseMessage 字段必空，按状态码派生）',
  },
  url: {
    icon: Link2,
    tooltip: '没拿到错误信息和 HTTP 标准描述，用请求 URL 兜底',
  },
  label: {
    icon: Tag,
    tooltip: '没拿到 URL 也没错误信息，用 sampler 名兜底',
  },
}
const BODY_ICON = {
  icon: FileJson,
  tooltip: '上方一行 = responseMessage / HTTP 派生；下方一行 = errors.xml 抓到的真实响应（已截断）',
}
</script>

<template>
  <div class="flex flex-col h-full min-h-0">
    <!-- 头：标题 + 摘要 -->
    <div
      class="flex items-baseline justify-between mb-2 pb-2 text-[12px]"
      :style="{
        color: isDark ? 'rgba(255,255,255,0.65)' : 'rgba(0,0,0,0.65)',
        borderBottom: `1px solid ${dividerColor}`,
      }"
    >
      <span>按接口分错误类型</span>
      <span
        v-if="groupCount"
        class="text-[11px] tabular-nums"
        :style="{ color: subColor }"
      >
        {{ groupCount }} 组合 · 共 {{ fmtInt(totalErrors) }} 错
      </span>
    </div>

    <!-- 空态 -->
    <div v-if="!displayRows.length" class="flex-1 flex items-center justify-center">
      <span class="text-[11.5px]" :style="{ color: subColor }">✓ 暂无错误样本</span>
    </div>

    <!-- 表 -->
    <div v-else class="flex-1 min-h-0 overflow-y-auto no-scrollbar">
      <table class="w-full text-[11.5px] tabular-nums">
        <thead class="sticky top-0" :style="{ background: isDark ? '#0f0f12' : '#f9f9fa' }">
          <tr :style="{ color: headerColor }">
            <th class="pb-2 px-1 w-[24px]"></th>
            <th class="text-left font-medium pb-2 px-2">接口</th>
            <th class="text-left font-medium pb-2 px-2 w-[68px]">code</th>
            <th class="pb-2 px-1 w-[28px]"></th>
            <th class="text-left font-medium pb-2 px-2">message</th>
            <th class="text-right font-medium pb-2 px-2 w-[60px]">count</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="(row, i) in displayRows" :key="i">
            <tr
              class="cursor-pointer"
              :style="{
                color: cellColor,
                borderTop: `1px solid ${dividerColor}`,
                background: expandedKey === rowKey(row)
                  ? (isDark ? 'rgba(239,68,68,0.06)' : 'rgba(239,68,68,0.04)')
                  : 'transparent',
              }"
              @click="toggleRow(row)"
              @mouseenter="(ev) => { if (expandedKey !== rowKey(row)) (ev.currentTarget as HTMLElement).style.background = isDark ? 'rgba(255,255,255,0.025)' : 'rgba(0,0,0,0.02)' }"
              @mouseleave="(ev) => { if (expandedKey !== rowKey(row)) (ev.currentTarget as HTMLElement).style.background = 'transparent' }"
            >
              <!-- chevron 列 -->
              <td class="py-1.5 px-1 align-middle">
                <component
                  :is="expandedKey === rowKey(row) ? ChevronDown : ChevronRight"
                  :size="12"
                  :color="isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)'"
                />
              </td>
              <!-- 接口 -->
              <td class="py-1.5 px-2 max-w-[260px]">
                <span class="truncate block" :title="row.label">{{ row.label }}</span>
              </td>
              <!-- code -->
              <td
                class="py-1.5 px-2 font-medium"
                :style="{ color: codeColor(row.responseCode) }"
              >
                {{ row.responseCode || '0' }}
              </td>
              <!-- source icon：拿到 body 时高亮 FileJson；否则按 primary 来源走 -->
              <td class="py-1.5 px-1 align-middle">
                <component
                  :is="row.hasBody ? BODY_ICON.icon : PRIMARY_META[row.primarySource].icon"
                  :size="13"
                  :stroke-width="2"
                  :title="row.hasBody ? BODY_ICON.tooltip : PRIMARY_META[row.primarySource].tooltip"
                  :style="{
                    color: row.hasBody
                      ? (isDark ? 'rgba(134,239,172,0.85)' : 'rgba(22,163,74,0.85)')
                      : (row.primarySource === 'message'
                          ? (isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.5)')
                          : (isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)')),
                    display: 'inline-block',
                  }"
                />
              </td>
              <!-- message：primary 一行 + 可选 secondary（body）小字一行 -->
              <td class="py-1.5 px-2 max-w-[320px]">
                <div class="flex flex-col gap-0.5 min-w-0">
                  <span
                    class="truncate"
                    :title="row.url && row.primarySource !== 'url' ? `${row.primary}\nURL: ${row.url}` : row.primary"
                  >{{ row.primary }}</span>
                  <span
                    v-if="row.secondary"
                    class="truncate text-[10.5px]"
                    :style="{ color: subColor }"
                    :title="row.secondary"
                  >{{ row.secondary }}</span>
                </div>
              </td>
              <!-- count -->
              <td class="py-1.5 px-2 text-right" :style="{ color: SEMANTIC.errors }">
                {{ fmtInt(row.count) }}
              </td>
            </tr>
            <!-- 展开行：SampleList 占满 6 列宽 -->
            <tr v-if="expandedKey === rowKey(row)">
              <td colspan="6" class="px-2 pb-2"
                  :style="{ background: isDark ? 'rgba(239,68,68,0.03)' : 'rgba(239,68,68,0.02)' }">
                <SampleList
                  :samples="samplesCache.get(rowKey(row)) ?? []"
                  :loading="samplesLoading.has(rowKey(row))"
                  :is-dark="isDark"
                />
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>
