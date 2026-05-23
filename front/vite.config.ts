import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
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
})

