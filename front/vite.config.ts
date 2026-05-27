/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
// 同时承担 Vite + Vitest 配置：
// - plugins / server / build 给 Vite 使用
// - test 给 Vitest 使用（jsdom 环境，加载 vitest.setup.ts，启用全局 API）
export default defineConfig({
  plugins: [react()],
  appType: 'spa',
  server: {
    port: 7788,
    open: true,
    headers: {
      'Cache-Control': 'no-store',
    },
    proxy: {
      '/api': {
        target: 'http://10.0.0.10:8000',
        changeOrigin: true,
      },
      '/openapi.json': {
        target: 'http://10.0.0.10:8000',
        changeOrigin: true,
      },
      '/metrics': {
        target: 'http://10.0.0.10:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    globals: true,
    css: false,
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
})
