<script setup lang="ts">
import { Layers } from 'lucide-vue-next'
import type { ThreadGroupInfo, ScenarioId } from '@/types/task'
import { scenarioById } from '../configStageCtx'

const props = defineProps<{
  threadGroups: ThreadGroupInfo[]      // 只含启用的 TG（ConfigStage 已过滤）
  scenarioByPath: Record<string, ScenarioId>
  currentPath: string
  isDark: boolean
}>()

defineEmits<{ (e: 'update:currentPath', path: string): void }>()
</script>

<template>
  <div
    v-if="threadGroups.length > 1"
    class="flex items-center gap-2 overflow-x-auto"
  >
    <Layers
      :size="13"
      :color="isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)'"
      class="flex-shrink-0"
    />
    <span
      class="text-[10px] uppercase tracking-[0.18em] mr-1 flex-shrink-0"
      :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
    >编辑中</span>
    <button
      v-for="tg in threadGroups"
      :key="tg.path"
      class="flex items-center gap-1.5 px-3 py-1 rounded-md text-[11.5px] flex-shrink-0 cursor-pointer"
      :style="{
        background: currentPath === tg.path
          ? (isDark ? 'rgba(139,92,246,0.15)' : 'rgba(139,92,246,0.1)')
          : (isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)'),
        color: currentPath === tg.path
          ? '#8b5cf6'
          : (isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.55)'),
        border: `1px solid ${currentPath === tg.path
          ? 'rgba(139,92,246,0.35)'
          : (isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)')}`,
      }"
      @click="$emit('update:currentPath', tg.path)"
    >
      <span>{{ tg.testname || `TG ${tg.path}` }}</span>
      <span
        v-if="scenarioByPath[tg.path]"
        class="text-[9px] px-1 rounded"
        :style="{
          background: scenarioById(scenarioByPath[tg.path]).color + '22',
          color: scenarioById(scenarioByPath[tg.path]).color,
        }"
      >{{ scenarioById(scenarioByPath[tg.path]).label }}</span>
    </button>
  </div>
</template>
