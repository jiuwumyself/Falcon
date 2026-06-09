<script setup lang="ts">
// Pod 网页终端：xterm.js ↔ 本地 WS 代理(/arthas-term) ↔ zapp-server Pod 终端。
// 连上后直接在里面跑 arthas / jstack 等；「保存到诊断」把近期输出回传给上层存库（喂 Step 4）。
import { onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { X, Save, Plug } from 'lucide-vue-next'

const props = defineProps<{
  cluster: string
  namespace: string
  pod: string
  container: string
  initCmd?: string      // 连上后自动执行（如自动 attach 进 arthas）
  isDark: boolean
}>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'capture', output: string): void }>()

const elRef = ref<HTMLDivElement | null>(null)
const status = ref<'connecting' | 'open' | 'closed'>('connecting')
const term = shallowRef<Terminal | null>(null)
let ws: WebSocket | null = null
let fit: FitAddon | null = null
let buffer = ''   // 累积近期输出，供「保存到诊断」

function connect() {
  const t = new Terminal({
    fontSize: 12, fontFamily: 'monospace', cursorBlink: true, convertEol: true,
    theme: props.isDark
      ? { background: '#0b0f17', foreground: '#d6deeb' }
      : { background: '#ffffff', foreground: '#1a1a2e', cursor: '#1a1a2e' },
  })
  term.value = t
  fit = new FitAddon()
  t.loadAddon(fit)
  if (elRef.value) t.open(elRef.value)
  setTimeout(() => fit?.fit(), 0)

  const qs = new URLSearchParams({ cluster: props.cluster, namespace: props.namespace, pod: props.pod, container: props.container })
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  ws = new WebSocket(`${proto}://${location.host}/arthas-term?${qs.toString()}`)
  ws.binaryType = 'arraybuffer'
  status.value = 'connecting'
  t.writeln('\x1b[90m[连接中…]\x1b[0m')

  let launched = false
  ws.onopen = () => { status.value = 'open'; setTimeout(() => fit?.fit(), 50) }
  ws.onmessage = (ev) => {
    const write = (s: string) => {
      t.write(s); buffer += s; if (buffer.length > 60000) buffer = buffer.slice(-50000)
      // 收到第一段输出（shell 提示符就绪）→ 自动执行 initCmd（如 attach 进 arthas）
      if (!launched && props.initCmd && ws && ws.readyState === WebSocket.OPEN) {
        launched = true
        setTimeout(() => { ws?.send(props.initCmd + '\n') }, 400)
      }
    }
    if (typeof ev.data === 'string') write(ev.data)
    else if (ev.data instanceof ArrayBuffer) write(new TextDecoder().decode(ev.data))
    else if (ev.data instanceof Blob) ev.data.text().then(write)
  }
  ws.onclose = () => { status.value = 'closed'; t.writeln('\r\n\x1b[90m[连接已关闭]\x1b[0m') }
  ws.onerror = () => { status.value = 'closed' }

  t.onData((data) => { if (ws && ws.readyState === WebSocket.OPEN) ws.send(data) })
}

function onResize() { fit?.fit() }
function saveOutput() {
  // 去掉 ANSI 转义，取近期可读输出回传上层
  const clean = buffer.replace(/\x1b\[[0-9;]*[A-Za-z]/g, '').replace(/\x1b\][^\x07]*\x07/g, '')
  emit('capture', clean.slice(-8000).trim())
}

onMounted(() => { connect(); window.addEventListener('resize', onResize) })
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  try { ws?.close() } catch { /* ignore */ }
  term.value?.dispose()
})
</script>

<template>
  <div class="rounded-lg overflow-hidden" :style="{ border: `1px solid ${isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.12)'}` }">
    <div class="flex items-center gap-2 px-2.5 py-1.5 text-[11px]"
         :style="{ background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)', color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)' }">
      <Plug :size="12" :color="status === 'open' ? '#10b981' : status === 'connecting' ? '#f59e0b' : '#ef4444'" />
      <span>{{ pod }} / {{ container }}</span>
      <span class="text-[10px]" :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }">
        {{ status === 'open' ? '已连接' : status === 'connecting' ? '连接中…' : '已断开' }}
      </span>
      <span class="flex-1" />
      <button class="inline-flex items-center gap-1 px-2 py-0.5 rounded" :style="{ color: '#10b981' }" title="把近期输出存到诊断（供 Step 4）" @click="saveOutput">
        <Save :size="12" />保存到诊断
      </button>
      <button class="inline-flex items-center gap-1 px-2 py-0.5 rounded" :style="{ color: isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.6)' }" @click="emit('close')">
        <X :size="12" />关闭
      </button>
    </div>
    <div ref="elRef" class="w-full" style="height:300px;background:#0b0f17" />
  </div>
</template>
