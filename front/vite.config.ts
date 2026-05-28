/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
// 同时承担 Vite + Vitest 配置：
// - plugins / server / build 给 Vite 使用
// - test 给 Vitest 使用（jsdom 环境，加载 vitest.setup.ts，启用全局 API）
//
// W32-followup-2 (Manual QA Bug C 修复)：
// 之前 proxy.target 写死 LAN IP（http://10.0.0.10:8000），开发者在本机
// 跑 backend :8088 时 proxy 整体走不通。改为读 VITE_BACKEND_URL env，
// 默认本机 127.0.0.1:8088（与 AGENTS.md 约定一致）。
const BACKEND_URL = process.env.VITE_BACKEND_URL || 'http://127.0.0.1:8088'

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
        target: BACKEND_URL,
        changeOrigin: true,
      },
      '/openapi.json': {
        target: BACKEND_URL,
        changeOrigin: true,
      },
      '/metrics': {
        target: BACKEND_URL,
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
