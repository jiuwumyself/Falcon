<script setup lang="ts">
import { reactive, watch } from 'vue'
import type { JSONAssertionDetail } from '@/types/task'

const props = defineProps<{ detail: JSONAssertionDetail; isDark: boolean }>()
const emit = defineEmits<{ (e: 'update:detail', next: JSONAssertionDetail): void }>()

const local = reactive<JSONAssertionDetail>({ ...props.detail })

// 防回环：父层用 `detail = $event` 接收，每次 emit 都是新对象引用，
// 会再次触发下面的 props 监听 → 回写 local → deep watch 再 emit …… 无限往返，
// 表现为抽屉里点「添加参数/添加文件」等操作后整个页面卡死（实测）。
// 用内容比对做守卫：与当前 local 等价的入参直接忽略，父层真改了才回写。
function sameAsLocal(d: unknown): boolean {
  try {
    return JSON.stringify(d) === JSON.stringify(local)
  } catch {
    return false
  }
}

watch(() => props.detail, (d) => {
  if (sameAsLocal(d)) return
  Object.assign(local, d)
})
watch(local, () => emit('update:detail', { ...local }), { deep: true })

const inputStyle = (isDark: boolean) => ({
  background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
  border: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
  color: isDark ? '#fff' : '#1a1a2e',
})
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-col gap-1">
      <label class="text-[11px]" :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }">JSONPath 表达式</label>
      <input
        v-model="local.jsonPath"
        type="text"
        placeholder="$.data.id"
        class="px-2.5 py-1.5 rounded-md text-[12px] font-mono outline-none"
        :style="inputStyle(isDark)"
      />
    </div>

    <div class="flex flex-col gap-1">
      <label class="text-[11px]" :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }">期望值</label>
      <input
        v-model="local.expectedValue"
        type="text"
        placeholder="200"
        class="px-2.5 py-1.5 rounded-md text-[12px] outline-none"
        :style="inputStyle(isDark)"
      />
    </div>

    <div class="flex flex-col gap-2">
      <label class="text-[11px]" :style="{ color: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)' }">选项</label>
      <div
        v-for="f in [
          { key: 'jsonValidation', label: 'JSON 验证（期望值非空时断言值）' },
          { key: 'expectNull', label: '期望为 null' },
          { key: 'invert', label: '反转断言（Not）' },
          { key: 'isRegex', label: '期望值使用正则' },
        ]"
        :key="f.key"
        class="flex items-center gap-2"
      >
        <input
          type="checkbox"
          :checked="(local as Record<string, string | boolean>)[f.key] as boolean"
          @change="(local as Record<string, string | boolean>)[f.key] = ($event.target as HTMLInputElement).checked"
        />
        <label class="text-[12px]" :style="{ color: isDark ? 'rgba(255,255,255,0.8)' : 'rgba(0,0,0,0.8)' }">{{ f.label }}</label>
      </div>
    </div>
  </div>
</template>
