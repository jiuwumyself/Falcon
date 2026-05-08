<script setup lang="ts">
import { computed } from 'vue'
import type { SamplerStat } from '@/types/task'
import { fmtInt } from './chartFactory'

const props = defineProps<{
  stats: SamplerStat[]
  isDark: boolean
}>()

const rows = computed(() =>
  props.stats
    .filter((s) => s.error > 0)
    .sort((a, b) => b.error - a.error)
    .slice(0, 50),
)

const headerColor = computed(() =>
  props.isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.5)',
)
const cellColor = computed(() =>
  props.isDark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.85)',
)
const dividerColor = computed(() =>
  props.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
)
</script>

<template>
  <div class="flex flex-col h-full min-h-0">
    <div
      class="text-center text-[12px] mb-2 pb-2"
      :style="{
        color: isDark ? 'rgba(255,255,255,0.65)' : 'rgba(0,0,0,0.65)',
        borderBottom: `1px solid ${dividerColor}`,
      }"
    >
      单个事务/接口的错误
    </div>
    <div v-if="!rows.length" class="flex-1 flex items-center justify-center">
      <span
        class="text-[11.5px]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
      >
        ✓ 暂无失败请求
      </span>
    </div>
    <div v-else class="flex-1 min-h-0 overflow-y-auto">
      <table class="w-full text-[11.5px] tabular-nums">
        <thead class="sticky top-0" :style="{ background: isDark ? '#0f0f12' : '#f9f9fa' }">
          <tr :style="{ color: headerColor }">
            <th class="text-left font-medium pb-2 px-2">transaction</th>
            <th class="text-right font-medium pb-2 px-2">sum</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.label"
            :style="{
              color: cellColor,
              borderTop: `1px solid ${dividerColor}`,
            }"
          >
            <td class="py-1.5 px-2 max-w-[260px]">
              <span class="truncate block" :title="row.label">{{ row.label }}</span>
            </td>
            <td class="py-1.5 px-2 text-right" :style="{ color: '#ef4444' }">
              {{ fmtInt(row.error) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
