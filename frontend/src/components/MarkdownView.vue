<script setup lang="ts">
// 把 markdown 文本渲染成排版好看的 HTML（marked 解析 + DOMPurify 清理防 XSS）。
// 用于 AI 分析结果等返回 markdown 的地方。暗/亮两套样式。
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const props = defineProps<{ source: string; isDark: boolean }>()

const html = computed(() => {
  const raw = marked.parse(props.source || '', { gfm: true, breaks: true }) as string
  return DOMPurify.sanitize(raw)
})
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -->
  <div class="md-body" :class="{ dark: isDark }" v-html="html" />
</template>

<style scoped>
.md-body { font-size: 12px; line-height: 1.65; color: rgba(0, 0, 0, 0.78); word-break: break-word; }
.md-body.dark { color: rgba(255, 255, 255, 0.8); }
.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3),
.md-body :deep(h4) { font-weight: 600; margin: 0.85em 0 0.4em; line-height: 1.3; color: #1a1a2e; }
.md-body.dark :deep(h1),
.md-body.dark :deep(h2),
.md-body.dark :deep(h3),
.md-body.dark :deep(h4) { color: #fff; }
.md-body :deep(h1) { font-size: 15px; }
.md-body :deep(h2) { font-size: 14px; }
.md-body :deep(h3) { font-size: 13px; }
.md-body :deep(h4) { font-size: 12.5px; }
.md-body :deep(p) { margin: 0.4em 0; }
.md-body :deep(ul),
.md-body :deep(ol) { margin: 0.4em 0; padding-left: 1.3em; }
.md-body :deep(li) { margin: 0.2em 0; }
.md-body :deep(strong) { font-weight: 600; color: #1a1a2e; }
.md-body.dark :deep(strong) { color: #fff; }
.md-body :deep(code) { font-family: monospace; font-size: 11px; background: rgba(0, 0, 0, 0.06); padding: 1px 4px; border-radius: 3px; }
.md-body.dark :deep(code) { background: rgba(255, 255, 255, 0.1); }
.md-body :deep(pre) { background: rgba(0, 0, 0, 0.05); padding: 8px 10px; border-radius: 6px; overflow-x: auto; margin: 0.5em 0; }
.md-body.dark :deep(pre) { background: rgba(0, 0, 0, 0.35); }
.md-body :deep(pre code) { background: none; padding: 0; font-size: 11px; }
.md-body :deep(table) { border-collapse: collapse; margin: 0.5em 0; font-size: 11px; width: 100%; }
.md-body :deep(th),
.md-body :deep(td) { border: 1px solid rgba(0, 0, 0, 0.12); padding: 4px 8px; text-align: left; }
.md-body.dark :deep(th),
.md-body.dark :deep(td) { border-color: rgba(255, 255, 255, 0.12); }
.md-body :deep(th) { background: rgba(0, 0, 0, 0.04); font-weight: 600; }
.md-body.dark :deep(th) { background: rgba(255, 255, 255, 0.06); }
.md-body :deep(hr) { border: none; border-top: 1px solid rgba(0, 0, 0, 0.1); margin: 0.8em 0; }
.md-body.dark :deep(hr) { border-top-color: rgba(255, 255, 255, 0.1); }
.md-body :deep(blockquote) { border-left: 3px solid rgba(0, 0, 0, 0.15); padding-left: 10px; margin: 0.5em 0; color: rgba(0, 0, 0, 0.6); }
.md-body.dark :deep(blockquote) { border-left-color: rgba(255, 255, 255, 0.15); color: rgba(255, 255, 255, 0.6); }
.md-body :deep(a) { color: #3b82f6; text-decoration: underline; }
.md-body :deep(:first-child) { margin-top: 0; }
.md-body :deep(:last-child) { margin-bottom: 0; }
</style>
