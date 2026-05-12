<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronDown, ChevronRight } from 'lucide-vue-next'
import type { ErrorSample } from '@/types/task'

// 聚合表行展开后内嵌的样本子列表。被 ErrorByEndpointTable 调用：
// 用户点聚合行 → 父组件拉 errorSamples(runId, {sampler, responseCode, limit:20})
// → 把 samples 数组传进来。
//
// **dedup**：sampler+code 已经一样，唯一可能不同的是 response_body / failure_message。
// 同 (body, reason) 算"同一种错误"，每组只显示首条 + ×N 徽章 + 时间范围。常见场景
// （服务端固定 reason）会把 165 条样本压成 1 行。
const props = defineProps<{
  samples: ErrorSample[]
  loading: boolean
  isDark: boolean
}>()

const expanded = ref<number | null>(null)

function fmtTime(ts: number): string {
  return new Date(ts).toLocaleTimeString('zh-CN', { hour12: false })
}

function singleLineReason(e: ErrorSample): string {
  return e.failure_message || e.response_message || e.response_code
}

function dedupKey(s: ErrorSample): string {
  return `${(s.response_body || '').trim()}||${singleLineReason(s)}`
}

interface SampleGroup {
  rep: ErrorSample
  count: number
  firstTs: number
  lastTs: number
  elapsedMin: number
  elapsedMax: number
}

const groups = computed<SampleGroup[]>(() => {
  const map = new Map<string, SampleGroup>()
  for (const s of props.samples) {
    const key = dedupKey(s)
    const g = map.get(key)
    if (!g) {
      map.set(key, {
        rep: s,
        count: 1,
        firstTs: s.timestamp,
        lastTs: s.timestamp,
        elapsedMin: s.elapsed_ms,
        elapsedMax: s.elapsed_ms,
      })
    } else {
      g.count++
      g.firstTs = Math.min(g.firstTs, s.timestamp)
      g.lastTs = Math.max(g.lastTs, s.timestamp)
      g.elapsedMin = Math.min(g.elapsedMin, s.elapsed_ms)
      g.elapsedMax = Math.max(g.elapsedMax, s.elapsed_ms)
    }
  }
  return Array.from(map.values()).sort((a, b) => b.count - a.count)
})

function elapsedLabel(g: SampleGroup): string {
  if (g.count === 1 || g.elapsedMin === g.elapsedMax) return `${g.elapsedMin}ms`
  return `${g.elapsedMin}–${g.elapsedMax}ms`
}
</script>

<template>
  <div class="pl-6 py-2 border-l-2"
       :style="{ borderColor: isDark ? 'rgba(239,68,68,0.25)' : 'rgba(239,68,68,0.3)' }">
    <div v-if="loading"
         class="text-[11px] py-1.5"
         :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }">
      加载样本…
    </div>

    <div v-else-if="!samples.length"
         class="text-[11px] py-1.5"
         :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }">
      该组合无可加载样本
    </div>

    <!-- 样本分组列表（按 body+reason dedup，每组 1 行 + ×N 徽章） -->
    <div v-else class="flex flex-col gap-0.5">
      <div v-for="(g, i) in groups" :key="i" class="flex flex-col">
        <button
          class="flex items-center gap-2 text-[11px] text-left py-1 px-1 rounded cursor-pointer"
          :style="{
            color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.85)',
          }"
          @click="expanded = expanded === i ? null : i"
          @mouseenter="(ev) => ((ev.currentTarget as HTMLElement).style.background = isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.025)')"
          @mouseleave="(ev) => ((ev.currentTarget as HTMLElement).style.background = '')"
        >
          <component
            :is="expanded === i ? ChevronDown : ChevronRight"
            :size="11"
            :color="isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)'"
            class="shrink-0"
          />
          <span class="tabular-nums shrink-0"
                :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }"
                :title="g.count > 1 ? `首条 ${new Date(g.firstTs).toLocaleString()}\n最后 ${new Date(g.lastTs).toLocaleString()}` : ''">
            <template v-if="g.count > 1">{{ fmtTime(g.firstTs) }}–{{ fmtTime(g.lastTs) }}</template>
            <template v-else>{{ fmtTime(g.rep.timestamp) }}</template>
          </span>
          <span class="font-medium tabular-nums shrink-0"
                :style="{ color: '#ef4444' }">{{ g.rep.response_code }}</span>
          <span v-if="g.count > 1"
                class="tabular-nums shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium"
                :style="{
                  background: isDark ? 'rgba(239,68,68,0.15)' : 'rgba(239,68,68,0.1)',
                  color: '#ef4444',
                }"
                :title="`折叠了 ${g.count} 条 body 完全相同的样本`">
            ×{{ g.count }}
          </span>
          <span class="tabular-nums shrink-0"
                :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">
            {{ elapsedLabel(g) }}
          </span>
          <span class="truncate flex-1"
                :style="{ color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)' }"
                :title="singleLineReason(g.rep)">
            {{ singleLineReason(g.rep) }}
          </span>
        </button>

        <div v-if="expanded === i" class="ml-5 mt-1 mb-1.5">
          <div class="text-[10px] uppercase tracking-wider mb-1"
               :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }">
            Response body
          </div>
          <pre
            class="text-[10.5px] p-2 rounded-md overflow-x-auto whitespace-pre-wrap break-all max-h-[200px] overflow-y-auto"
            :style="{
              background: isDark ? 'rgba(0,0,0,0.4)' : 'rgba(0,0,0,0.04)',
              color: isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.85)',
              border: `1px solid ${isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'}`,
            }"
          >{{ g.rep.response_body || '(空响应体)' }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>
