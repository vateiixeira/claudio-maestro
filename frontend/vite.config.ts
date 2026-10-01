/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

// Same variables as the backend (MAESTRO_PORT, MAESTRO_DEV_PORT); validated there.
const devPort = Number(process.env.MAESTRO_DEV_PORT || 6600)
const backend = `http://127.0.0.1:${Number(process.env.MAESTRO_PORT || 6660)}`

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    host: '127.0.0.1',
    port: devPort,
    strictPort: true,
    proxy: {
      '/api': { target: backend },
      '/ws': { target: backend, ws: true },
    },
  },
  test: {
    environment: 'jsdom',
  },
})
