<script setup lang="ts">
import { ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    value: number
    suffix?: string
    decimals?: number
    trigger: boolean
  }>(),
  { suffix: '', decimals: 0 },
)

const display = ref('0')
let ran = false

watch(
  () => props.trigger,
  (t) => {
    if (!t || ran) return
    ran = true
    const start = performance.now()
    const go = (now: number) => {
      const p = Math.min((now - start) / 1400, 1)
      const e = 1 - Math.pow(1 - p, 4)
      display.value =
        props.decimals > 0
          ? (e * props.value).toFixed(props.decimals)
          : Math.floor(e * props.value).toLocaleString()
      if (p < 1) requestAnimationFrame(go)
    }
    requestAnimationFrame(go)
  },
  { immediate: true },
)
</script>

<template>
  <span>{{ display }}{{ suffix }}</span>
</template>
