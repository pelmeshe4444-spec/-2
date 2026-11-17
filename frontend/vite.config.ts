import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  base: process.env.VITE_BASE_PATH || '/',
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: {
    rollupOptions: { output: { manualChunks(id) {
      if (/\/node_modules\/(react|react-dom|scheduler)\//.test(id)) return 'react'
      if (/\/node_modules\/(recharts|victory-vendor|d3-[^/]+)\//.test(id)) return 'charts'
    } } },
  },
})
