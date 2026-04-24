<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

interface Particle {
  x: number
  y: number
  vx: number
  vy: number
  size: number
  alpha: number
  color: string
  life: number
  maxLife: number
}

const canvasRef = ref<HTMLCanvasElement | null>(null)

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const mouse = { x: -1000, y: -1000 }
  const particles: Particle[] = []
  let raf = 0

  const resize = () => {
    canvas.width = canvas.offsetWidth * window.devicePixelRatio
    canvas.height = canvas.offsetHeight * window.devicePixelRatio
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio)
  }
  resize()
  window.addEventListener('resize', resize)

  const w = () => canvas.offsetWidth
  const h = () => canvas.offsetHeight
  const colors = ['#3b82f6', '#60a5fa', '#7c3aed', '#a78bfa', '#818cf8']

  const createParticle = (): Particle => {
    const angle = Math.random() * Math.PI * 2
    const dist = Math.random() * Math.max(w(), h()) * 0.8
    const cx = w() / 2
    const cy = h() / 2
    const maxLife = 200 + Math.random() * 300
    const x = cx + Math.cos(angle) * dist
    const y = cy + Math.sin(angle) * dist
    return {
      x,
      y,
      vx: (cx - x) * 0.002,
      vy: (cy - y) * 0.002,
      size: Math.random() * 2 + 0.5,
      alpha: Math.random() * 0.6 + 0.2,
      color: colors[Math.floor(Math.random() * colors.length)],
      life: 0,
      maxLife,
    }
  }

  for (let i = 0; i < 150; i++) {
    const p = createParticle()
    p.life = Math.random() * p.maxLife
    particles.push(p)
  }

  const handleMouse = (e: MouseEvent) => {
    const rect = canvas.getBoundingClientRect()
    mouse.x = e.clientX - rect.left
    mouse.y = e.clientY - rect.top
  }
  canvas.addEventListener('mousemove', handleMouse)

  const animate = () => {
    ctx.clearRect(0, 0, w(), h())
    const { x: mx, y: my } = mouse

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i]
      p.life++
      if (p.life > p.maxLife) {
        particles[i] = createParticle()
        continue
      }

      const dx = p.x - mx
      const dy = p.y - my
      const d = Math.sqrt(dx * dx + dy * dy)
      if (d < 120 && d > 0) {
        const force = (120 - d) / 120
        p.vx += (dx / d) * force * 0.3
        p.vy += (dy / d) * force * 0.3
      }

      const cx = w() / 2
      const cy = h() / 2
      p.vx += (cx - p.x) * 0.00008
      p.vy += (cy - p.y) * 0.00008

      p.vx *= 0.99
      p.vy *= 0.99
      p.x += p.vx
      p.y += p.vy

      const lifeRatio = p.life / p.maxLife
      const fadeAlpha = lifeRatio < 0.1 ? lifeRatio * 10 : lifeRatio > 0.8 ? (1 - lifeRatio) * 5 : 1

      ctx.beginPath()
      ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2)
      ctx.fillStyle = p.color
      ctx.globalAlpha = p.alpha * fadeAlpha
      ctx.fill()

      ctx.beginPath()
      ctx.arc(p.x, p.y, p.size * 3, 0, Math.PI * 2)
      const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.size * 3)
      grad.addColorStop(0, p.color)
      grad.addColorStop(1, 'transparent')
      ctx.fillStyle = grad
      ctx.globalAlpha = p.alpha * fadeAlpha * 0.3
      ctx.fill()
    }

    ctx.globalAlpha = 1
    raf = requestAnimationFrame(animate)
  }

  animate()

  onBeforeUnmount(() => {
    cancelAnimationFrame(raf)
    window.removeEventListener('resize', resize)
    canvas.removeEventListener('mousemove', handleMouse)
  })
})
</script>

<template>
  <canvas ref="canvasRef" class="absolute inset-0 w-full h-full" style="opacity: 0.8" />
</template>
