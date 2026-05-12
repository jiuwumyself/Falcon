<script setup lang="ts">
import { computed } from 'vue'
import { ExternalLink, FileText } from 'lucide-vue-next'
import { runsApi } from '@/lib/api'
import type { TaskRun } from '@/types/task'

// JMeter `-e -o report/` 生成的 HTML 报告 iframe 嵌入。报告跟当前选中 run 走；
// success 终态最有用（含 Apdex / 各 sampler 表 / 完整图），其他状态可能只有半成品或不存在。
const props = defineProps<{
  run: TaskRun | null
  isDark: boolean
}>()

const reportUrl = computed(() => {
  if (!props.run?.run_id) return ''
  return runsApi.reportUrl(props.run.run_id)
})

// success 才大概率有完整报告；其他状态显示提示但仍允许尝试加载
const isSuccess = computed(() => props.run?.status === 'success')
const muted = computed(() => props.isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.55)')
</script>

<template>
  <div class="h-full flex flex-col min-h-0">
    <!-- 头：状态提示 + 新窗口打开链接 -->
    <div
      class="flex items-center justify-between gap-2 px-3 py-2 text-[11.5px] flex-shrink-0"
      :style="{
        borderBottom: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
      }"
    >
      <div class="flex items-center gap-1.5" :style="{ color: muted }">
        <FileText :size="12" />
        <span v-if="!run">未选择 run</span>
        <span v-else-if="isSuccess">JMeter HTML 报告 · run {{ run.run_id }}</span>
        <span v-else>
          当前 run 状态为 <b>{{ run.status }}</b>，报告可能不完整或不存在
        </span>
      </div>
      <a
        v-if="reportUrl"
        :href="reportUrl"
        target="_blank"
        rel="noopener"
        class="flex items-center gap-1 px-2 py-0.5 rounded cursor-pointer"
        :style="{
          color: isDark ? '#93c5fd' : '#2563eb',
          background: isDark ? 'rgba(59,130,246,0.12)' : 'rgba(59,130,246,0.08)',
        }"
      >
        <ExternalLink :size="11" />
        新窗口打开
      </a>
    </div>

    <!-- iframe：没 run / 没 url 时显示占位 -->
    <div v-if="!reportUrl" class="flex-1 flex items-center justify-center text-[12px]"
         :style="{ color: muted }">
      选中一个历史 run 后此处显示对应报告
    </div>
    <iframe
      v-else
      :key="reportUrl"
      :src="reportUrl"
      class="flex-1 w-full border-0"
      style="background: #fff"
    />
  </div>
</template>
