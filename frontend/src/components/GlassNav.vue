<script setup lang="ts">
withDefaults(defineProps<{ class?: string }>(), { class: '' })
</script>

<template>
  <div
    :class="['rounded-[28px] relative overflow-hidden', $props.class]"
    style="
      background: var(--card);
      backdrop-filter: blur(48px);
      -webkit-backdrop-filter: blur(48px);
      box-shadow: inset 0 1px 0 0 rgba(255,255,255,0.08), 0 8px 32px rgba(0,0,0,0.12), 0 0 0 1px rgba(255,255,255,0.06);
      border: 1px solid rgba(255,255,255,0.06);
    "
  >
    <slot />
  </div>
</template>
