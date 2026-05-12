<script setup lang="ts">
import { ref } from 'vue'
import { ChevronDown, ChevronRight } from 'lucide-vue-next'
import type { ErrorSample } from '@/types/task'

// 聚合表行展开后内嵌的样本子列表。被 ErrorByEndpointTable 调用：
// 用户点聚合行 → 父组件拉 errorSamples(runId, {sampler, responseCode, limit:20})
// → 把 samples 数组传进来。每条样本可二级展开看 response_body。
//
// 单一职责：「展示一组 ErrorSample，含可展开 body」。不管轮询 / 拉数据 / 过滤。
defineProps<{
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
</script>

<template>
  <div class="pl-6 py-2 border-l-2"
       :style="{ borderColor: isDark ? 'rgba(239,68,68,0.25)' : 'rgba(239,68,68,0.3)' }">
    <!-- 加载 -->
    <div v-if="loading"
         class="text-[11px] py-1.5"
         :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }">
      加载样本…
    </div>

    <!-- 空（理论上不会发生：聚合行 count > 0 但拉不到样本只可能是 jtl 损坏 / 后端 bug） -->
    <div v-else-if="!samples.length"
         class="text-[11px] py-1.5"
         :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }">
      该组合无可加载样本
    </div>

    <!-- 样本列表 -->
    <div v-else class="flex flex-col gap-0.5">
      <div v-for="(s, i) in samples" :key="i" class="flex flex-col">
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
                :style="{ color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)' }">
            {{ fmtTime(s.timestamp) }}
          </span>
          <span class="font-medium tabular-nums shrink-0"
                :style="{ color: '#ef4444' }">{{ s.response_code }}</span>
          <span class="tabular-nums shrink-0"
                :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }">
            {{ s.elapsed_ms }}ms
          </span>
          <span class="truncate flex-1"
                :style="{ color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)' }"
                :title="singleLineReason(s)">
            {{ singleLineReason(s) }}
          </span>
        </button>

        <!-- 二级展开：response_body -->
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
          >{{ s.response_body || '(空响应体)' }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>
