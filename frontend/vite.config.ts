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
        proxyTimeout: 60_000,
        timeout: 60_000,
      },
    },
  },
})
