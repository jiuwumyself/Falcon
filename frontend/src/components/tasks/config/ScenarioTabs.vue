<script setup lang="ts">
import { computed } from 'vue'
import { Motion } from 'motion-v'
import type { ScenarioId } from '@/types/task'
import { SCENARIOS, scenarioById } from '../configStageCtx'

const props = defineProps<{
  modelValue: ScenarioId
  isDark: boolean
}>()

const emit = defineEmits<{ (e: 'update:modelValue', v: ScenarioId): void }>()

const current = computed(() => scenarioById(props.modelValue))
</script>

<template>
  <div class="flex flex-col gap-3">
    <!-- Pills row -->
    <div class="flex gap-2 flex-wrap">
      <button
        v-for="s in SCENARIOS"
        :key="s.id"
        class="relative flex items-center gap-1.5 px-3.5 py-2 rounded-full text-[12px] transition-all cursor-pointer select-none"
        :style="{
          background: modelValue === s.id
            ? `linear-gradient(135deg, ${s.color}, ${s.color}cc)`
            : (isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)'),
          color: modelValue === s.id
            ? '#fff'
            : (isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.65)'),
          border: modelValue === s.id
            ? `1px solid ${s.color}`
            : `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
          transform: modelValue === s.id ? 'scale(1.04)' : 'scale(1)',
          boxShadow: modelValue === s.id
            ? `0 4px 14px ${s.color}55, 0 0 0 4px ${s.color}22`
            : 'none',
        }"
        @click="emit('update:modelValue', s.id)"
      >
        <component :is="s.icon" :size="13" />
        <span>{{ s.label }}</span>
        <!-- selected indicator: small dot on upper-right -->
        <span
          v-if="modelValue === s.id"
          class="absolute -top-1 -right-1 w-2 h-2 rounded-full"
          :style="{ background: '#fff', boxShadow: `0 0 0 2px ${s.color}` }"
        />
      </button>
    </div>

    <!-- Description bar (always visible when something is selected) -->
    <Motion
      :key="current.id"
      :initial="{ opacity: 0, y: -4 }"
      :animate="{ opacity: 1, y: 0 }"
      :transition="{ duration: 0.2 }"
      class="rounded-lg px-3 py-2 flex items-start gap-2 text-[12px] leading-relaxed"
      :style="{
        background: `${current.color}14`,
        border: `1px solid ${current.color}33`,
        color: isDark ? '#e8e8ed' : '#1a1a2e',
      }"
    >
      <div
        class="w-1 self-stretch rounded-full flex-shrink-0"
        :style="{ background: current.color }"
      />
      <div class="flex-1">
        <strong class="font-medium" :style="{ color: current.color }">
          {{ current.label }}
        </strong>
        <span class="ml-2">{{ current.desc }}</span>
      </div>
    </Motion>
  </div>
</template>
