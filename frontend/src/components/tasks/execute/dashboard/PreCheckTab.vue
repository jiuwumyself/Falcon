<script setup lang="ts">
import PreCheckPanel from '../PreCheckPanel.vue'

const props = defineProps<{
  log: string
  isDark: boolean
}>()
</script>

<template>
  <div class="h-full overflow-y-auto">
    <p
      v-if="!props.log"
      class="text-[12px] py-6 text-center"
      :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
    >
      暂无预检日志。run 启动后会自动写入。
    </p>
    <PreCheckPanel v-else :log="props.log" :is-dark="isDark" />
  </div>
</template>
