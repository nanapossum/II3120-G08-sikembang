import path from 'node:path'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

// Mode "live": proxy /api ke backend lewat VITE_DEV_PROXY_TARGET supaya tidak perlu CORS saat development.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react(), tailwindcss()],
    resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
    server: {
      port: 5173,
      proxy: env.VITE_DEV_PROXY_TARGET
        ? { '/api': { target: env.VITE_DEV_PROXY_TARGET, changeOrigin: true } }
        : undefined,
    },
    test: { environment: 'node', include: ['src/**/*.test.ts'] },
  }
})
