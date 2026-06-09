<script setup lang="ts">
// Arthas 智能诊断面板：关键命令速查 + 按「服务诊断」数据闪烁推荐对症命令 + 记录命令输出存库（供 Step 4）。
// 网页终端接入前：点命令=复制，在脚本终端里跑 arthas，把关键输出粘回「记录输出」保存。
import { computed, onMounted, ref, watch } from 'vue'
import { Terminal, Zap, Copy, Save, Trash2, ChevronDown, ChevronRight, Loader2 } from 'lucide-vue-next'
import { runsApi } from '@/lib/api'
import PodTerminal from './PodTerminal.vue'
import type { ArthasCapture, DiagnosisResponse } from '@/types/task'

const props = defineProps<{
  data: DiagnosisResponse | null
  runId: string | null
  service: string
  isDark: boolean
}>()
const d = (l: string, dk: string) => (props.isDark ? dk : l)

// ── 命令目录（关键命令置顶，按用途分组）──
interface ArCmd { cmd: string; desc: string; cat: string; tags: string[] }
const CMDS: ArCmd[] = [
  { cmd: 'dashboard', desc: '实时面板：线程/内存/GC/运行时一屏看（先看它）', cat: '概览', tags: ['gc', 'cpu', 'thread', 'heap'] },
  { cmd: 'thread -n 3', desc: '最忙的 3 个线程（定位 CPU 飙高）', cat: '线程/CPU', tags: ['cpu'] },
  { cmd: 'thread -b', desc: '找出阻塞其他线程的线程（死锁/锁竞争）', cat: '线程/CPU', tags: ['thread', 'block'] },
  { cmd: 'thread', desc: '所有线程状态分布', cat: '线程/CPU', tags: ['thread'] },
  { cmd: 'profiler start  / profiler stop --format html', desc: '采样火焰图，看 CPU 热点方法', cat: '线程/CPU', tags: ['cpu'] },
  { cmd: 'jvm', desc: 'JVM 各项指标（含 GC 次数/耗时/各代）', cat: '内存/GC', tags: ['gc', 'heap'] },
  { cmd: 'memory', desc: '内存各区使用（堆/非堆/各代）', cat: '内存/GC', tags: ['heap', 'gc'] },
  { cmd: 'vmoption', desc: '看/改 JVM 运行参数（如打开 PrintGC）', cat: '内存/GC', tags: ['gc'] },
  { cmd: 'heapdump /tmp/dump.hprof', desc: '导出堆快照排查内存泄漏（注意暂停）', cat: '内存/GC', tags: ['heap'] },
  { cmd: 'trace 类 方法', desc: '方法内部各调用耗时（定位慢在哪一段）', cat: '方法追踪', tags: ['slow'] },
  { cmd: 'watch 类 方法 "{params,returnObj,throwExp}" -x 2', desc: '观察入参/返回/异常', cat: '方法追踪', tags: ['slow', 'error'] },
  { cmd: 'stack 类 方法', desc: '方法调用栈（谁调用的）', cat: '方法追踪', tags: ['slow'] },
  { cmd: 'tt -t 类 方法', desc: '记录调用上下文，事后回放复现', cat: '方法追踪', tags: ['error'] },
  { cmd: 'jad 类', desc: '反编译看线上真实代码', cat: '类', tags: ['class'] },
  { cmd: 'sc -d 类', desc: '查类信息 / 类加载器', cat: '类', tags: ['class'] },
  { cmd: 'logger --name xxx --level debug', desc: '动态调日志级别排查错误', cat: '其他', tags: ['error'] },
]
const CATS = ['概览', '线程/CPU', '内存/GC', '方法追踪', '类', '其他']

// ── 按诊断数据生成「检测到的问题」+ 推荐 tag ──
interface Reco { tags: string[]; reason: string; sev: 'high' | 'mid' }
const recos = computed<Reco[]>(() => {
  const out: Reco[] = []
  const j = props.data?.jvm
  const gc = j?.gc
  if (gc && gc.old_count > 0) out.push({ tags: ['gc', 'heap'], reason: `Full GC ${gc.old_count} 次 / ${gc.old_time_ms}ms`, sev: 'high' })
  const at = props.data?.active_threads
  if (at && at.max >= 50) out.push({ tags: ['thread', 'cpu'], reason: `活跃线程峰值 ${at.max}`, sev: 'mid' })
  const slow = (props.data?.uri_stat || []).filter((u) => u.max_ms >= 1000)
  if (slow.length) out.push({ tags: ['slow'], reason: `${slow.length} 个慢接口（最慢 ${Math.max(...slow.map((s) => s.max_ms))}ms）`, sev: 'mid' })
  const errs = props.data?.error_uris || []
  if (errs.length) out.push({ tags: ['error', 'slow'], reason: `${errs.length} 个失败接口（最多 ×${errs[0]?.fail_count}）`, sev: 'high' })
  const tx = props.data?.transactions
  if (tx && tx.error_rate > 1) out.push({ tags: ['error'], reason: `错误率 ${tx.error_rate}%`, sev: 'high' })
  return out
})
const recoTags = computed(() => new Set(recos.value.flatMap((r) => r.tags)))
const isReco = (c: ArCmd) => c.tags.some((t) => recoTags.value.has(t))

// ── 点命令 = 复制 + 带入「记录输出」表单 ──
const draftCmd = ref('')
const draftOut = ref('')
const draftNote = ref('')
const showSaver = ref(false)
const copiedCmd = ref('')
function onCmd(c: ArCmd) {
  navigator.clipboard?.writeText(c.cmd).catch(() => {})
  copiedCmd.value = c.cmd
  setTimeout(() => { if (copiedCmd.value === c.cmd) copiedCmd.value = '' }, 1200)
  draftCmd.value = c.cmd
  showSaver.value = true
}

// ── 已存输出 ──
const captures = ref<ArthasCapture[]>([])
const saving = ref(false)
const expandedCap = ref<number | null>(null)
async function loadCaptures() {
  if (!props.runId) { captures.value = []; return }
  try { captures.value = await runsApi.arthasCaptures(props.runId, props.service) } catch { /* ignore */ }
}
async function save() {
  if (!props.runId || !draftCmd.value.trim() || saving.value) return
  saving.value = true
  try {
    const cap = await runsApi.saveArthasCapture(props.runId, {
      service: props.service, command: draftCmd.value.trim(), output: draftOut.value, note: draftNote.value.trim(),
    })
    captures.value = [cap, ...captures.value]
    draftOut.value = ''; draftNote.value = ''
  } catch { /* ignore */ } finally { saving.value = false }
}
async function removeCap(id: number) {
  if (!props.runId) return
  try { await runsApi.deleteArthasCapture(props.runId, id); captures.value = captures.value.filter((c) => c.id !== id) } catch { /* ignore */ }
}
const fmtTime = (s: string) => new Date(s).toLocaleString('zh-CN', { hour12: false }).slice(5)

watch([() => props.runId, () => props.service], loadCaptures, { immediate: true })

// ── 网页终端：级联选 集群→命名空间→pod（实时取自 zapp-server，免手填）──
const showTerm = ref(false)
const autoArthas = ref(true)   // 连上即自动 attach 进 arthas
// 自动启动：jps 找业务 java 进程(排除 arthas-boot/jps 自身)→ arthas-boot attach；容器内拿不到就退 PID 1
const ARTHAS_LAUNCH = "PID=$(jps -l 2>/dev/null | grep -v arthas-boot | grep -v sun.tools | head -1 | awk '{print $1}'); java -jar /opt/arthas/arthas-boot.jar ${PID:-1}"
const term = ref({ cluster: '', namespace: '', pod: '', container: '' })
const clusters = ref<{ id: number; name: string }[]>([])
const namespaces = ref<string[]>([])
const podList = ref<{ pod: string; namespace: string; containers: string[] }[]>([])
const loadErr = ref('')
const loadingC = ref(false), loadingN = ref(false), loadingP = ref(false)

const LS_KEY = computed(() => `arthas-pick-${props.service}`)
async function loadClusters() {
  loadingC.value = true; loadErr.value = ''
  try { clusters.value = await runsApi.arthasClusters() }
  catch (e) { loadErr.value = e instanceof Error ? e.message : String(e) }
  finally { loadingC.value = false }
}
async function onCluster() {
  namespaces.value = []; podList.value = []; term.value.namespace = ''; term.value.pod = ''; term.value.container = ''
  if (!term.value.cluster) return
  loadingN.value = true
  try { namespaces.value = await runsApi.arthasNamespaces(term.value.cluster) } catch { /* ignore */ } finally { loadingN.value = false }
}
async function onNamespace(autoFirst = true) {
  podList.value = []; term.value.pod = ''; term.value.container = ''
  if (!term.value.cluster || !term.value.namespace) return
  loadingP.value = true
  try {
    podList.value = await runsApi.arthasPods(term.value.cluster, term.value.namespace, props.service)
    if (autoFirst && podList.value.length) setPod(podList.value[0].pod)   // 自动选第一个 pod
  } catch { /* ignore */ } finally { loadingP.value = false }
}
function setPod(p: string) {
  term.value.pod = p
  const hit = podList.value.find((x) => x.pod === p)
  term.value.container = hit?.containers?.[0] || props.service
}
function startTerm() {
  if (!term.value.pod || !term.value.namespace || !term.value.cluster) return
  // 记住这个服务上次选的集群+命名空间，下次自动带出
  try { localStorage.setItem(LS_KEY.value, JSON.stringify({ cluster: term.value.cluster, namespace: term.value.namespace })) } catch { /* ignore */ }
  showTerm.value = true
}
function onCapture(output: string) {
  draftCmd.value = draftCmd.value || '终端会话'
  draftOut.value = output
  showSaver.value = true
}
// 恢复上次选择：集群+命名空间自动带出 → pod 自动列好，你直接选 pod / 连接
async function restore() {
  let saved: { cluster: string; namespace: string } | null = null
  try { saved = JSON.parse(localStorage.getItem(LS_KEY.value) || 'null') } catch { /* ignore */ }
  if (!saved?.cluster) return
  term.value.cluster = String(saved.cluster)
  await onCluster()
  if (saved.namespace && namespaces.value.includes(saved.namespace)) {
    term.value.namespace = saved.namespace
    await onNamespace()
  }
}
onMounted(async () => { await loadClusters(); await restore() })
</script>

<template>
  <div class="rounded-xl p-3" :style="{ background: d('rgba(255,255,255,0.6)', 'rgba(255,255,255,0.02)'), border: `1px solid ${d('rgba(0,0,0,0.06)', 'rgba(255,255,255,0.06)')}` }">
    <div class="flex items-center gap-2 mb-2 flex-wrap">
      <span class="w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0" style="background:#0f6e56"><Terminal :size="13" color="#fff" /></span>
      <span class="text-[13px] font-medium" :style="{ color: d('rgba(0,0,0,0.75)', 'rgba(255,255,255,0.78)') }">Arthas 诊断</span>
      <span class="flex-1" />
      <span class="text-[10px]" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">需开 arthas_ws_proxy</span>
    </div>

    <!-- 网页终端：级联选 集群→命名空间→pod（实时取自 zapp-server，免手填）-->
    <div v-if="!showTerm" class="flex items-end gap-1.5 flex-wrap mb-2 p-2 rounded-lg" :style="{ background: d('rgba(0,0,0,0.02)', 'rgba(255,255,255,0.02)') }">
      <label class="flex flex-col gap-0.5">
        <span class="text-[9px]" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">集群 {{ loadingC ? '…' : '' }}</span>
        <select v-model="term.cluster" @change="onCluster" class="text-[11px] w-40 px-1.5 py-1 rounded outline-none cursor-pointer" :style="{ background: d('#fff', 'rgba(255,255,255,0.06)'), color: d('#1a1a2e', '#fff'), border: `1px solid ${d('rgba(0,0,0,0.1)', 'rgba(255,255,255,0.12)')}` }">
          <option value="" :style="{ background: d('#fff', '#1a2330') }">选集群</option>
          <option v-for="c in clusters" :key="c.id" :value="c.id" :style="{ background: d('#fff', '#1a2330') }">{{ c.id }} · {{ c.name }}</option>
        </select>
      </label>
      <label class="flex flex-col gap-0.5">
        <span class="text-[9px]" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">命名空间 {{ loadingN ? '…' : '' }}</span>
        <select v-model="term.namespace" @change="onNamespace()" :disabled="!term.cluster" class="text-[11px] w-28 px-1.5 py-1 rounded outline-none cursor-pointer disabled:opacity-50" :style="{ background: d('#fff', 'rgba(255,255,255,0.06)'), color: d('#1a1a2e', '#fff'), border: `1px solid ${d('rgba(0,0,0,0.1)', 'rgba(255,255,255,0.12)')}` }">
          <option value="" :style="{ background: d('#fff', '#1a2330') }">选 ns</option>
          <option v-for="n in namespaces" :key="n" :value="n" :style="{ background: d('#fff', '#1a2330') }">{{ n }}</option>
        </select>
      </label>
      <label class="flex flex-col gap-0.5 min-w-0">
        <span class="text-[9px]" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">pod {{ loadingP ? '…' : (podList.length ? '(' + podList.length + ')' : '') }}</span>
        <select v-model="term.pod" @change="setPod(term.pod)" :disabled="!podList.length" class="text-[11px] w-56 px-1.5 py-1 rounded outline-none cursor-pointer disabled:opacity-50" style="font-family:monospace" :style="{ background: d('#fff', 'rgba(255,255,255,0.06)'), color: d('#1a1a2e', '#fff'), border: `1px solid ${d('rgba(0,0,0,0.1)', 'rgba(255,255,255,0.12)')}` }">
          <option value="" :style="{ background: d('#fff', '#1a2330') }">{{ term.namespace && !podList.length && !loadingP ? '该 ns 无 ' + service : '选 pod' }}</option>
          <option v-for="p in podList" :key="p.pod" :value="p.pod" :style="{ background: d('#fff', '#1a2330') }">{{ p.pod }}</option>
        </select>
      </label>
      <span v-if="term.container" class="text-[10px] pb-1.5" :style="{ color: d('rgba(0,0,0,0.45)', 'rgba(255,255,255,0.45)') }">容器 {{ term.container }}</span>
      <button :disabled="!term.pod" @click="startTerm"
              class="text-[11px] px-3 py-1.5 rounded-md inline-flex items-center gap-1 disabled:opacity-40 disabled:cursor-not-allowed" style="color:#fff;background:#0f6e56">
        <Terminal :size="12" />连接终端
      </button>
      <label class="flex items-center gap-1 text-[10.5px] cursor-pointer" :style="{ color: d('rgba(0,0,0,0.55)', 'rgba(255,255,255,0.55)') }">
        <input type="checkbox" v-model="autoArthas" />连上即进 Arthas
      </label>
      <span v-if="loadErr" class="text-[10px] pb-1.5" style="color:#ef4444">{{ loadErr }}</span>
    </div>
    <PodTerminal v-else :cluster="term.cluster" :namespace="term.namespace" :pod="term.pod" :container="term.container"
                 :init-cmd="autoArthas ? ARTHAS_LAUNCH : ''" :is-dark="isDark"
                 @close="showTerm = false" @capture="onCapture" class="mb-2" />

    <!-- 检测到的问题 → 高亮推荐 -->
    <div v-if="recos.length" class="rounded-lg p-2 mb-2"
         :style="{ background: d('rgba(245,158,11,0.08)', 'rgba(245,158,11,0.1)'), border: `1px solid ${d('rgba(245,158,11,0.25)', 'rgba(245,158,11,0.25)')}` }">
      <div class="flex items-center gap-1.5 mb-1">
        <Zap :size="12" color="#f59e0b" />
        <span class="text-[11px] font-medium" :style="{ color: d('#92590c', '#fbbf24') }">据诊断数据检测到：闪烁的命令是对症推荐</span>
      </div>
      <div class="flex flex-wrap gap-1.5">
        <span v-for="(r, i) in recos" :key="i" class="text-[10.5px] px-1.5 py-0.5 rounded"
              :style="{ color: r.sev === 'high' ? '#ef4444' : '#b45309', background: d('rgba(0,0,0,0.03)', 'rgba(255,255,255,0.05)') }">{{ r.reason }}</span>
      </div>
    </div>

    <!-- 命令速查 -->
    <div class="flex flex-col gap-1.5 mb-2">
      <template v-for="cat in CATS" :key="cat">
        <div v-if="CMDS.some((c) => c.cat === cat)" class="flex items-start gap-2">
          <span class="text-[10px] w-14 flex-shrink-0 pt-1" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">{{ cat }}</span>
          <div class="flex flex-wrap gap-1 flex-1 min-w-0">
            <button v-for="c in CMDS.filter((x) => x.cat === cat)" :key="c.cmd" @click="onCmd(c)"
                    class="text-[11px] px-2 py-1 rounded-md inline-flex items-center gap-1 transition-colors text-left"
                    :class="{ 'arthas-flash': isReco(c) }"
                    :title="c.desc + '（点击复制命令）'"
                    :style="{
                      background: isReco(c) ? d('rgba(245,158,11,0.14)', 'rgba(245,158,11,0.18)') : d('rgba(0,0,0,0.04)', 'rgba(255,255,255,0.06)'),
                      color: isReco(c) ? d('#92590c', '#fbbf24') : d('rgba(0,0,0,0.72)', 'rgba(255,255,255,0.78)'),
                      border: `1px solid ${isReco(c) ? 'rgba(245,158,11,0.4)' : 'transparent'}`,
                      fontFamily: 'monospace',
                    }">
              <Zap v-if="isReco(c)" :size="10" />
              {{ c.cmd.length > 34 ? c.cmd.slice(0, 33) + '…' : c.cmd }}
              <Copy v-if="copiedCmd === c.cmd" :size="10" />
            </button>
          </div>
        </div>
      </template>
    </div>

    <!-- 记录输出（存库供 Step 4）-->
    <div class="rounded-lg" :style="{ border: `1px solid ${d('rgba(0,0,0,0.06)', 'rgba(255,255,255,0.08)')}` }">
      <button class="w-full flex items-center gap-1.5 px-2.5 py-1.5 text-[11.5px]" :style="{ color: d('rgba(0,0,0,0.65)', 'rgba(255,255,255,0.7)') }" @click="showSaver = !showSaver">
        <component :is="showSaver ? ChevronDown : ChevronRight" :size="13" />
        <Save :size="12" />记录诊断输出
        <span v-if="captures.length" class="text-[10px] px-1.5 rounded-full" :style="{ background: d('rgba(0,0,0,0.06)', 'rgba(255,255,255,0.1)'), color: d('rgba(0,0,0,0.5)', 'rgba(255,255,255,0.5)') }">{{ captures.length }}</span>
        <span class="flex-1" />
        <span v-if="!runId" class="text-[10px]" :style="{ color: d('rgba(0,0,0,0.4)', 'rgba(255,255,255,0.4)') }">需选具体 run 才能存</span>
      </button>
      <div v-if="showSaver" class="px-2.5 pb-2.5 flex flex-col gap-2">
        <!-- 录入表单 -->
        <div v-if="runId" class="flex flex-col gap-1.5">
          <input v-model="draftCmd" placeholder="命令（点上面命令会自动带入）" class="text-[11px] px-2 py-1 rounded outline-none"
                 style="font-family:monospace" :style="{ background: d('rgba(0,0,0,0.03)', 'rgba(255,255,255,0.05)'), color: d('#1a1a2e', '#fff'), border: `1px solid ${d('rgba(0,0,0,0.08)', 'rgba(255,255,255,0.1)')}` }" />
          <textarea v-model="draftOut" rows="4" placeholder="把 arthas 的关键输出粘贴到这里（如 dashboard / jvm 截取）" class="text-[11px] px-2 py-1 rounded outline-none resize-y"
                    style="font-family:monospace" :style="{ background: d('rgba(0,0,0,0.03)', 'rgba(255,255,255,0.05)'), color: d('#1a1a2e', '#fff'), border: `1px solid ${d('rgba(0,0,0,0.08)', 'rgba(255,255,255,0.1)')}` }" />
          <div class="flex items-center gap-2">
            <input v-model="draftNote" placeholder="备注/结论（如：Full GC 频繁，疑似内存泄漏）" class="flex-1 text-[11px] px-2 py-1 rounded outline-none"
                   :style="{ background: d('rgba(0,0,0,0.03)', 'rgba(255,255,255,0.05)'), color: d('#1a1a2e', '#fff'), border: `1px solid ${d('rgba(0,0,0,0.08)', 'rgba(255,255,255,0.1)')}` }" />
            <button :disabled="!draftCmd.trim() || saving" @click="save"
                    class="text-[11px] px-3 py-1 rounded-md inline-flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed" style="color:#fff;background:#10b981">
              <Loader2 v-if="saving" :size="12" class="animate-spin" /><Save v-else :size="12" />保存
            </button>
          </div>
        </div>
        <!-- 已存列表 -->
        <div v-for="cap in captures" :key="cap.id" class="rounded-md" :style="{ background: d('rgba(0,0,0,0.02)', 'rgba(255,255,255,0.03)') }">
          <div class="flex items-center gap-2 px-2 py-1">
            <code class="text-[11px] flex-shrink-0" :style="{ color: d('#2563eb', '#93c5fd') }">{{ cap.command }}</code>
            <span class="text-[10.5px] truncate flex-1" :style="{ color: d('rgba(0,0,0,0.6)', 'rgba(255,255,255,0.6)') }">{{ cap.note }}</span>
            <span class="text-[10px] flex-shrink-0" :style="{ color: d('rgba(0,0,0,0.35)', 'rgba(255,255,255,0.35)') }">{{ fmtTime(cap.created_at) }}</span>
            <button v-if="cap.output" @click="expandedCap = expandedCap === cap.id ? null : cap.id" class="text-[10px]" :style="{ color: d('rgba(0,0,0,0.45)', 'rgba(255,255,255,0.45)') }">{{ expandedCap === cap.id ? '收起' : '展开' }}</button>
            <button @click="removeCap(cap.id)" class="flex-shrink-0" :style="{ color: 'rgba(239,68,68,0.7)' }"><Trash2 :size="12" /></button>
          </div>
          <pre v-if="expandedCap === cap.id" class="text-[10.5px] px-2 pb-2 overflow-x-auto whitespace-pre-wrap" :style="{ color: d('rgba(0,0,0,0.7)', 'rgba(255,255,255,0.7)') }">{{ cap.output }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@keyframes arthasFlash {
  0%, 100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0); }
  50% { box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.35); }
}
.arthas-flash { animation: arthasFlash 1.4s ease-in-out infinite; }
</style>
