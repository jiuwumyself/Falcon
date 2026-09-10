import { defineConfig } from 'vite'
import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // 大 run（百万错误，3.7GB errors xml）下 sampler-stats / error-samples
        // 端点要 3-5s，留充裕 buffer 避免 vite-proxy 偶发 502
        proxyTimeout: 120_000,
        timeout: 120_000,
      },
      // Django admin（后台入口在 MainLayout 的齿轮）：生产同域由 nginx 转发，
      // dev 下 5173 不认这个路径会被 vue-router 接管成白屏，所以这里代理到后端。
      // /static 是 admin 自带的 css/js，runserver 会 serve。
      '/admin': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/static': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // Arthas Pod 终端：WS 转发到本地代理（scripts/arthas_ws_proxy.py，:8011）
      '/arthas-term': {
        target: 'ws://localhost:8011',
        ws: true,
        changeOrigin: true,
      },
    },
  },
})
