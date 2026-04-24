<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    data: number[]
    color: string
    w?: number
    h?: number
    threshold?: number
    uid?: string
  }>(),
  { w: 280, h: 56, threshold: 95, uid: 'x' },
)

const lava = '#f97316'

const pts = computed(() => {
  const mn = Math.min(...props.data) - 1
  const mx = Math.max(...props.data) + 1
  const rg = mx - mn
  return props.data.map((v, i) => ({
    x: (i / (props.data.length - 1)) * props.w,
    y: props.h - ((v - mn) / rg) * props.h,
    v,
  }))
})

const areaPath = computed(() => {
  const p = pts.value
  let a = ''
  p.forEach((pt, i) => {
    if (!i) a = `M ${pt.x} ${pt.y}`
    else {
      const prev = p[i - 1]
      const cpx = (prev.x + pt.x) / 2
      a += ` C ${cpx} ${prev.y}, ${cpx} ${pt.y}, ${pt.x} ${pt.y}`
    }
  })
  return `${a} L ${props.w} ${props.h} L 0 ${props.h} Z`
})

const segments = computed(() => {
  const p = pts.value
  const segs: { d: string; bad: boolean; key: number }[] = []
  for (let i = 1; i < p.length; i++) {
    const prev = p[i - 1]
    const pt = p[i]
    const cpx = (prev.x + pt.x) / 2
    const bad = props.threshold > 0 && (pt.v < props.threshold || prev.v < props.threshold)
    segs.push({
      key: i,
      bad,
      d: `M ${prev.x} ${prev.y} C ${cpx} ${prev.y}, ${cpx} ${pt.y}, ${pt.x} ${pt.y}`,
    })
  }
  return segs
})
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
      <linearGradient :id="`g${uid}`" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" :stop-color="color" stop-opacity="0.2" />
        <stop offset="100%" :stop-color="color" stop-opacity="0" />
      </linearGradient>
      <filter :id="`f${uid}`">
        <feGaussianBlur stdDeviation="3" result="b" />
        <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
      </filter>
    </defs>
    <path :d="areaPath" :fill="`url(#g${uid})`" />
    <path
      v-for="s in segments"
      :key="s.key"
      :d="s.d"
      fill="none"
      :stroke="s.bad ? lava : color"
      stroke-width="2.5"
      :filter="`url(#f${uid})`"
    />
    <circle
      v-for="(p, i) in pts"
      :key="i"
      :cx="p.x"
      :cy="p.y"
      r="2.5"
      :fill="threshold > 0 && p.v < threshold ? lava : color"
      opacity="0.9"
    />
  </svg>
</template>
