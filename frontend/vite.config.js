import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      { find: /^process$/, replacement: "process/browser" },
      { find: "buffer", replacement: "buffer" },
      { find: "stream", replacement: "stream-browserify" },
      { find: "util", replacement: "util" },
    ],
  },
  define: {
    global: 'globalThis',
    'process.env': {},
    'process.version': '"v24.14.1"',
  },
  optimizeDeps: {
    include: ['buffer', 'process'],
  },
})