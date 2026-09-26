import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { realpathSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  // Use the canonical checkout root so Vite and Rollup agree when this project
  // is reached through a Windows directory junction.
  root: realpathSync(fileURLToPath(new URL('.', import.meta.url))),
  plugins: [react()],
  resolve: {
    alias: [
      { find: /^process$/, replacement: 'process/browser' },
      { find: 'buffer', replacement: 'buffer' },
      { find: 'stream', replacement: 'stream-browserify' },
      { find: 'util', replacement: 'util' },
    ],
  },
  define: {
    global: 'globalThis',
    'process.env': {},
  },
  optimizeDeps: {
    include: ['buffer', 'process'],
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'solana-core': ['@solana/web3.js', '@project-serum/anchor'],
          'wallet-adapters': [
            '@solana/wallet-adapter-base',
            '@solana/wallet-adapter-phantom',
            '@solana/wallet-adapter-react',
            '@solana/wallet-adapter-react-ui',
            '@solana/wallet-adapter-solflare',
          ],
        },
      },
    },
  },
});
