<script setup lang="ts">
import { reactive, computed, watch } from 'vue'
import type { BeanShellDetail } from '@/types/task'

const props = defineProps<{ detail: BeanShellDetail; isDark: boolean }>()
const emit = defineEmits<{ (e: 'update:detail', next: BeanShellDetail): void }>()

const local = reactive<BeanShellDetail>({ ...props.detail })

watch(() => props.detail, (d) => Object.assign(local, d))
watch(local, () => emit('update:detail', { ...local }), { deep: true })

const isPreProcessor = computed(() => local.kind === 'BeanShellPreProcessor')

const inputStyle = (isDark: boolean) => ({
  background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
  border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
  color: isDark ? '#fff' : '#1a1a2e',
})
</script>

<template>
  <div class="flex flex-col gap-4">
    <p
      class="text-[11px]"
      :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
    >{{ isPreProcessor ? 'BeanShell 预处理器' : 'BeanShell 后置处理器' }}</p>

    <div class="flex flex-col gap-1">
      <label class="text-[11px]" :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }">脚本</label>
      <textarea
        v-model="local.script"
        rows="14"
        placeholder="// BeanShell / Groovy 脚本"
        class="px-2.5 py-2 rounded-md text-[12px] font-mono outline-none resize-y"
        :style="inputStyle(isDark)"
      />
    </div>

    <div class="flex flex-col gap-1">
      <label class="text-[11px]" :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }">参数（空格分隔）</label>
      <input
        v-model="local.parameters"
        type="text"
        placeholder=""
        class="px-2.5 py-1.5 rounded-md text-[12px] outline-none"
        :style="inputStyle(isDark)"
      />
    </div>

    <div class="flex items-center gap-2">
      <input
        type="checkbox"
        :checked="local.resetInterpreter"
        @change="local.resetInterpreter = ($event.target as HTMLInputElement).checked"
      />
      <label class="text-[12px]" :style="{ color: isDark ? 'rgba(255,255,255,0.8)' : 'rgba(0,0,0,0.8)' }">
        每次迭代重置解释器
      </label>
    </div>
  </div>
</template>
