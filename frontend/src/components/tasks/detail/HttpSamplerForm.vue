<script setup lang="ts">
import { reactive, watch } from 'vue'
import { Plus, Trash2 } from 'lucide-vue-next'
import type { HttpSamplerDetail } from '@/types/task'

const props = defineProps<{ detail: HttpSamplerDetail; isDark: boolean }>()
const emit = defineEmits<{ (e: 'update:detail', next: HttpSamplerDetail): void }>()

// Deep-copy the incoming detail so we can edit freely without mutating parent.
function clone(d: HttpSamplerDetail): HttpSamplerDetail {
  return {
    kind: 'HTTPSamplerProxy',
    domain: d.domain,
    port: d.port,
    protocol: d.protocol,
    method: d.method,
    path: d.path,
    bodyMode: d.bodyMode,
    params: d.params.map((p) => ({ ...p })),
    body: d.body,
    files: d.files.map((f) => ({ ...f })),
  }
}

const local = reactive<HttpSamplerDetail>(clone(props.detail))

watch(
  () => props.detail,
  (d) => Object.assign(local, clone(d)),
)
watch(local, () => emit('update:detail', clone(local)), { deep: true })

const PROTOCOLS = ['', 'http', 'https']
const METHODS = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS']

function addParam() { local.params.push({ name: '', value: '' }) }
function removeParam(i: number) { local.params.splice(i, 1) }
function addFile() { local.files.push({ path: '', paramname: '', mimetype: '' }) }
function removeFile(i: number) { local.files.splice(i, 1) }

function inputStyle(dark: boolean) {
  return {
    background: dark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
    border: `1px solid ${dark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'}`,
    color: dark ? '#fff' : '#1a1a2e',
  }
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <!-- ─ Basic ─────────────────────────────────── -->
    <section class="flex flex-col gap-3">
      <h3
        class="text-[10px] uppercase tracking-[0.2em]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }"
      >基础</h3>

      <div>
        <label
          class="block text-[10px] uppercase tracking-wider mb-1"
          :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
        >Domain</label>
        <input
          v-model="local.domain"
          type="text"
          placeholder="example.com"
          class="w-full px-3 py-2 rounded-md text-[13px] outline-none"
          :style="inputStyle(isDark)"
        />
      </div>

      <div class="grid grid-cols-2 gap-3">
        <div>
          <label
            class="block text-[10px] uppercase tracking-wider mb-1"
            :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
          >Port</label>
          <input
            v-model="local.port"
            type="text"
            placeholder="80"
            class="w-full px-3 py-2 rounded-md text-[13px] outline-none"
            :style="inputStyle(isDark)"
          />
        </div>
        <div>
          <label
            class="block text-[10px] uppercase tracking-wider mb-1"
            :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
          >Protocol</label>
          <select
            v-model="local.protocol"
            class="w-full px-3 py-2 rounded-md text-[13px] outline-none"
            :style="inputStyle(isDark)"
          >
            <option v-for="p in PROTOCOLS" :key="p" :value="p">{{ p || '(继承)' }}</option>
          </select>
        </div>
      </div>

      <div>
        <label
          class="block text-[10px] uppercase tracking-wider mb-1"
          :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
        >Method</label>
        <select
          v-model="local.method"
          class="w-full px-3 py-2 rounded-md text-[13px] outline-none"
          :style="inputStyle(isDark)"
        >
          <option v-for="m in METHODS" :key="m" :value="m">{{ m }}</option>
        </select>
      </div>

      <div>
        <label
          class="block text-[10px] uppercase tracking-wider mb-1"
          :style="{ color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)' }"
        >Path</label>
        <input
          v-model="local.path"
          type="text"
          placeholder="/api/login"
          class="w-full px-3 py-2 rounded-md text-[13px] font-mono outline-none"
          :style="inputStyle(isDark)"
        />
      </div>
    </section>

    <!-- ─ Body / Params ────────────────────────── -->
    <section class="flex flex-col gap-2">
      <div class="flex items-center justify-between">
        <h3
          class="text-[10px] uppercase tracking-[0.2em]"
          :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }"
        >请求内容</h3>
        <!-- Mode switch: segmented control -->
        <div
          class="flex rounded-md p-0.5"
          :style="{ background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)' }"
        >
          <button
            class="px-3 py-1 rounded-[5px] text-[11px] transition-colors cursor-pointer"
            :style="{
              background: local.bodyMode === 'params'
                ? (isDark ? 'rgba(255,255,255,0.09)' : 'rgba(255,255,255,0.95)')
                : 'transparent',
              color: local.bodyMode === 'params'
                ? (isDark ? '#fff' : '#1a1a2e')
                : (isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)'),
            }"
            @click="local.bodyMode = 'params'"
          >参数</button>
          <button
            class="px-3 py-1 rounded-[5px] text-[11px] transition-colors cursor-pointer"
            :style="{
              background: local.bodyMode === 'raw'
                ? (isDark ? 'rgba(255,255,255,0.09)' : 'rgba(255,255,255,0.95)')
                : 'transparent',
              color: local.bodyMode === 'raw'
                ? (isDark ? '#fff' : '#1a1a2e')
                : (isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)'),
            }"
            @click="local.bodyMode = 'raw'"
          >消息体</button>
        </div>
      </div>

      <!-- Params mode: key/value list -->
      <template v-if="local.bodyMode === 'params'">
        <div
          v-for="(p, i) in local.params"
          :key="i"
          class="flex items-center gap-2"
        >
          <input
            v-model="p.name"
            type="text"
            placeholder="name"
            class="flex-1 px-2.5 py-1.5 rounded-md text-[12px] font-mono outline-none"
            :style="inputStyle(isDark)"
          />
          <input
            v-model="p.value"
            type="text"
            placeholder="value"
            class="flex-[2] px-2.5 py-1.5 rounded-md text-[12px] font-mono outline-none"
            :style="inputStyle(isDark)"
          />
          <button
            class="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0 cursor-pointer"
            :style="{
              background: isDark ? 'rgba(239,68,68,0.1)' : 'rgba(239,68,68,0.08)',
              color: '#ef4444',
              border: `1px solid ${isDark ? 'rgba(239,68,68,0.2)' : 'rgba(239,68,68,0.18)'}`,
            }"
            @click="removeParam(i)"
          >
            <Trash2 :size="12" />
          </button>
        </div>
        <p
          v-if="!local.params.length"
          class="text-[11px] py-2"
          :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)' }"
        >还没有参数，点下面加一行。</p>
        <button
          class="px-3 py-2 rounded-md text-[12px] flex items-center justify-center gap-1.5 cursor-pointer"
          :style="{
            background: isDark ? 'rgba(59,130,246,0.08)' : 'rgba(59,130,246,0.06)',
            color: '#3b82f6',
            border: `1px dashed ${isDark ? 'rgba(59,130,246,0.3)' : 'rgba(59,130,246,0.3)'}`,
          }"
          @click="addParam"
        >
          <Plus :size="12" />
          添加参数
        </button>
      </template>

      <!-- Raw body mode: textarea -->
      <template v-else>
        <textarea
          v-model="local.body"
          placeholder='{"key": "value"}'
          rows="8"
          class="w-full px-3 py-2 rounded-md text-[12px] font-mono outline-none resize-y"
          :style="inputStyle(isDark)"
        />
        <p
          class="text-[10px]"
          :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)' }"
        >写入 `postBodyRaw=true`，整段文本作为请求体发送（需在 HeaderManager 里加匹配的 Content-Type）。</p>
      </template>
    </section>

    <!-- ─ Files ─────────────────────────────────── -->
    <section class="flex flex-col gap-2">
      <h3
        class="text-[10px] uppercase tracking-[0.2em]"
        :style="{ color: isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)' }"
      >文件上传 (multipart)</h3>

      <div
        v-for="(f, i) in local.files"
        :key="i"
        class="flex flex-col gap-1.5 p-2 rounded-md"
        :style="{
          background: isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)',
          border: `1px solid ${isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
        }"
      >
        <div class="flex items-center gap-2">
          <input
            v-model="f.path"
            type="text"
            placeholder="/path/to/file"
            class="flex-1 px-2.5 py-1 rounded-md text-[12px] font-mono outline-none"
            :style="inputStyle(isDark)"
          />
          <button
            class="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0 cursor-pointer"
            :style="{
              background: isDark ? 'rgba(239,68,68,0.1)' : 'rgba(239,68,68,0.08)',
              color: '#ef4444',
              border: `1px solid ${isDark ? 'rgba(239,68,68,0.2)' : 'rgba(239,68,68,0.18)'}`,
            }"
            @click="removeFile(i)"
          >
            <Trash2 :size="12" />
          </button>
        </div>
        <div class="flex items-center gap-2">
          <input
            v-model="f.paramname"
            type="text"
            placeholder="paramName"
            class="flex-1 px-2.5 py-1 rounded-md text-[11px] font-mono outline-none"
            :style="inputStyle(isDark)"
          />
          <input
            v-model="f.mimetype"
            type="text"
            placeholder="image/jpeg"
            class="flex-1 px-2.5 py-1 rounded-md text-[11px] font-mono outline-none"
            :style="inputStyle(isDark)"
          />
        </div>
      </div>

      <p
        v-if="!local.files.length"
        class="text-[11px] py-2"
        :style="{ color: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)' }"
      >没有要上传的文件。</p>
      <button
        class="px-3 py-2 rounded-md text-[12px] flex items-center justify-center gap-1.5 cursor-pointer"
        :style="{
          background: isDark ? 'rgba(59,130,246,0.08)' : 'rgba(59,130,246,0.06)',
          color: '#3b82f6',
          border: `1px dashed ${isDark ? 'rgba(59,130,246,0.3)' : 'rgba(59,130,246,0.3)'}`,
        }"
        @click="addFile"
      >
        <Plus :size="12" />
        添加文件
      </button>
    </section>
  </div>
</template>
