import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
      '/video_feed': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
      '/unknown': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
      '/exports': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
})
