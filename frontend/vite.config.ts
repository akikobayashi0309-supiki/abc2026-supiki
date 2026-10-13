import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // In production Firebase Hosting rewrites /api/** to Cloud Run.
    proxy: { '/api': 'http://localhost:8080' },
  },
})
