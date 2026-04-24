<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{ data: number[]; color: string; w?: number; h?: number }>(),
  { w: 160, h: 24 },
)

const uid = `w${Math.random().toString(36).slice(2, 7)}`

const pts = computed(() => {
  const mn = Math.min(...props.data) * 0.8
  const mx = Math.max(...props.data) * 1.1
  const rg = mx - mn || 1
  return props.data.map((v, i) => ({
    x: (i / (props.data.length - 1)) * props.w,
    y: props.h - ((v - mn) / rg) * props.h,
  }))
})

const pathD = computed(() => {
  const p = pts.value
  let a = ''
  p.forEach((pt, i) => {
    if (!i) a = `M ${pt.x} ${pt.y}`
    else {
      const prev = p[i - 1]
      const cx = (prev.x + pt.x) / 2
      a += ` C ${cx} ${prev.y}, ${cx} ${pt.y}, ${pt.x} ${pt.y}`
    }
  })
  return a
})

const areaPath = computed(() => `${pathD.value} L ${props.w} ${props.h} L 0 ${props.h} Z`)
</script>

<template>
  <svg
    width="100%"
    :height="h"
    :viewBox="`0 0 ${w} ${h}`"
    preserveAspectRatio="none"
    class="overflow-visible"
  >
    <defs>
      <linearGradient :id="`wg${uid}`" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" :stop-color="color" stop-opacity="0.2" />
        <stop offset="100%" :stop-color="color" stop-opacity="0" />
      </linearGradient>
      <filter :id="`wf${uid}`">
        <feGaussianBlur stdDeviation="2" result="b" />
        <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
      </filter>
    </defs>
    <path :d="areaPath" :fill="`url(#wg${uid})`" />
    <path
      :d="pathD"
      fill="none"
      :stroke="color"
      stroke-width="1.2"
      :filter="`url(#wf${uid})`"
      opacity="0.7"
    />
  </svg>
</template>
