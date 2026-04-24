<script setup lang="ts">
import { ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{ value: number; decimals?: number; suffix?: string }>(),
  { decimals: 0, suffix: '' },
)

const display = ref('0')
let ran = false

function run() {
  ran = true
  const start = performance.now()
  const target = props.value
  const step = (now: number) => {
    const p = Math.min((now - start) / 1100, 1)
    const e = 1 - Math.pow(1 - p, 4)
    display.value =
      props.decimals > 0
        ? (e * target).toFixed(props.decimals)
        : Math.floor(e * target).toLocaleString()
    if (p < 1) requestAnimationFrame(step)
  }
  requestAnimationFrame(step)
}

watch(() => props.value, () => { if (!ran) run() }, { immediate: true })
</script>

<template><span>{{ display }}{{ suffix }}</span></template>
