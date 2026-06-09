import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5175,
    strictPort: true,
    host: '127.0.0.1',
    proxy: {
      // 默认 8000（与 start-all.bat / run_dev.bat 一致）；8000 被占用时 run_dev.ps1 会切到 8001，需设 VITE_API_TARGET
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
        timeout: 120000,
      },
    },
  },
})
