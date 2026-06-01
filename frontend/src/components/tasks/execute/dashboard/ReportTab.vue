<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ExternalLink, FileText, FileBarChart, Loader2, AlertCircle } from 'lucide-vue-next'
import { runsApi } from '@/lib/api'
import type { TaskRun } from '@/types/task'

// JMeter 原生 HTML 报告**按需生成**:跑压测不再带 -e -o(省开销/不留 report temp),
// 用户点"生成报告"才跑 jmeter -g,成功后删 results.jtl 腾盘。显示/分析全走 DB,这个
// tab 只是想看 JMeter 原生仪表板时才用。
const props = defineProps<{
  run: TaskRun | null
  isDark: boolean
}>()

type View = 'loading' | 'ready' | 'can_generate' | 'cleaned' | 'none'

const status = ref<{ state: 'none' | 'ready'; has_jtl: boolean } | null>(null)
const loading = ref(false)
const generating = ref(false)
const genError = ref('')

const reportUrl = computed(() =>
  props.run?.run_id ? runsApi.reportUrl(props.run.run_id) : '',
)
const muted = computed(() => props.isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.55)')

const view = computed<View>(() => {
  if (!props.run?.run_id) return 'none'
  if (loading.value && !status.value) return 'loading'
  const s = status.value
  if (!s) return 'loading'
  if (s.state === 'ready') return 'ready'
  return s.has_jtl ? 'can_generate' : 'cleaned'
})

async function fetchStatus() {
  if (!props.run?.run_id) { status.value = null; return }
  loading.value = true
  genError.value = ''
  try {
    status.value = await runsApi.reportStatus(props.run.run_id)
  } catch {
    status.value = null
  } finally {
    loading.value = false
  }
}

async function onGenerate() {
  if (!props.run?.run_id || generating.value) return
  generating.value = true
  genError.value = ''
  try {
    status.value = await runsApi.generateReport(props.run.run_id)
  } catch (e) {
    genError.value = e instanceof Error ? e.message : String(e)
  } finally {
    generating.value = false
  }
}

watch(() => props.run?.run_id, fetchStatus, { immediate: true })
</script>

<template>
  <div class="h-full flex flex-col min-h-0">
    <!-- 头：状态 + 新窗口打开（仅 ready）-->
    <div
      class="flex items-center justify-between gap-2 px-3 py-2 text-[11.5px] flex-shrink-0"
      :style="{ borderBottom: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}` }"
    >
      <div class="flex items-center gap-1.5" :style="{ color: muted }">
        <FileText :size="12" />
        <span v-if="!run">未选择 run</span>
        <span v-else-if="view === 'ready'">JMeter 原生报告 · run {{ run.run_id }}</span>
        <span v-else>JMeter 原生 HTML 报告（按需生成）</span>
      </div>
      <a
        v-if="view === 'ready' && reportUrl"
        :href="reportUrl"
        target="_blank"
        rel="noopener"
        class="flex items-center gap-1 px-2 py-0.5 rounded cursor-pointer"
        :style="{
          color: isDark ? '#93c5fd' : '#2563eb',
          background: isDark ? 'rgba(59,130,246,0.12)' : 'rgba(59,130,246,0.08)',
        }"
      >
        <ExternalLink :size="11" />
        新窗口打开
      </a>
    </div>

    <!-- ready：嵌入面板 -->
    <iframe
      v-if="view === 'ready'"
      :key="reportUrl"
      :src="reportUrl"
      class="flex-1 w-full border-0"
      style="background: #fff"
    />

    <!-- can_generate：生成按钮 -->
    <div v-else-if="view === 'can_generate'"
         class="flex-1 flex flex-col items-center justify-center gap-3 px-6 text-center">
      <FileBarChart :size="32" :style="{ color: muted }" />
      <div class="text-[12.5px]" :style="{ color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)' }">
        点击生成 JMeter 原生 HTML 报告（含 Apdex / 各接口表 / 完整图表）
      </div>
      <div class="text-[11px] max-w-[440px]" :style="{ color: muted }">
        生成会从 results.jtl 跑一遍 jmeter -g（大文件需几秒~几分钟），<b>成功后会删除原始
        results.jtl 腾出磁盘</b>。报告即生成后的静态页面，趋势/接口统计/错误明细等不依赖它。
      </div>
      <button
        class="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-[12px] cursor-pointer disabled:opacity-60"
        :style="{ color: '#fff', background: '#2563eb' }"
        :disabled="generating"
        @click="onGenerate"
      >
        <Loader2 v-if="generating" :size="13" class="animate-spin" />
        <FileBarChart v-else :size="13" />
        {{ generating ? '生成中…' : '生成报告' }}
      </button>
      <div v-if="genError" class="flex items-center gap-1 text-[11px]" style="color:#ef4444">
        <AlertCircle :size="11" /> {{ genError }}
      </div>
    </div>

    <!-- cleaned：JTL 已清理且无报告 -->
    <div v-else-if="view === 'cleaned'"
         class="flex-1 flex flex-col items-center justify-center gap-2 px-6 text-center"
         :style="{ color: muted }">
      <AlertCircle :size="28" />
      <div class="text-[12px]">原始 results.jtl 已清理，无法再生成原生报告</div>
      <div class="text-[11px] max-w-[420px]">
        该 run 的接口统计 / 错误明细 / 并发 / 趋势等数据已入库，去对应 tab 查看即可。
      </div>
    </div>

    <!-- loading / none -->
    <div v-else class="flex-1 flex items-center justify-center gap-2 text-[12px]"
         :style="{ color: muted }">
      <Loader2 v-if="view === 'loading'" :size="14" class="animate-spin" />
      <span>{{ view === 'loading' ? '加载报告状态…' : '选中一个历史 run 后此处显示对应报告' }}</span>
    </div>
  </div>
</template>
