<script setup lang="ts">
import { Motion } from 'motion-v'

withDefaults(defineProps<{ size?: number }>(), { size: 40 })
</script>

<template>
  <Motion
    as="svg"
    :width="size"
    :height="size"
    viewBox="0 0 64 64"
    fill="none"
    :initial="{ opacity: 0 }"
    :animate="{ opacity: 1 }"
    :transition="{ duration: 0.6 }"
  >
    <defs>
      <linearGradient id="falconGrad" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#38bdf8" />
        <stop offset="50%" stop-color="#818cf8" />
        <stop offset="100%" stop-color="#c084fc" />
      </linearGradient>
      <linearGradient id="falconMetal" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#93c5fd" />
        <stop offset="30%" stop-color="#c4b5fd" />
        <stop offset="50%" stop-color="#67e8f9" />
        <stop offset="70%" stop-color="#a5b4fc" />
        <stop offset="100%" stop-color="#f0abfc" />
      </linearGradient>
      <filter id="falconGlow">
        <feGaussianBlur stdDeviation="2" result="blur" />
        <feMerge>
          <feMergeNode in="blur" />
          <feMergeNode in="SourceGraphic" />
        </feMerge>
      </filter>
    </defs>
    <path
      d="M16 44 L32 12 L40 28"
      stroke="url(#falconMetal)"
      stroke-width="3.5"
      stroke-linecap="round"
      stroke-linejoin="round"
      fill="none"
    />
    <path
      d="M22 42 L36 16 L48 36"
      stroke="url(#falconMetal)"
      stroke-width="2.5"
      stroke-linecap="round"
      stroke-linejoin="round"
      fill="none"
      opacity="0.7"
    />
    <path
      d="M28 40 L38 20 L52 40"
      stroke="url(#falconMetal)"
      stroke-width="1.5"
      stroke-linecap="round"
      stroke-linejoin="round"
      fill="none"
      opacity="0.4"
    />
    <Motion
      as="circle"
      cx="35"
      cy="22"
      r="2"
      fill="url(#falconGrad)"
      filter="url(#falconGlow)"
      :initial="{ opacity: 0.3 }"
      :animate="{ opacity: [0.2, 0.4, 0.2] }"
      :transition="{ duration: 3, repeat: Infinity }"
    />
  </Motion>
</template>
