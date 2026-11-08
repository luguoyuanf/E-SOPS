import { fileURLToPath } from 'node:url';

import Vue from '@vitejs/plugin-vue';
import { defineConfig } from 'vite';

export default defineConfig({
  root: fileURLToPath(new URL('./public-download', import.meta.url)),
  base: '/public-download/',
  publicDir: false,
  plugins: [Vue()],
  resolve: { dedupe: ['vue'] },
  build: {
    outDir: fileURLToPath(new URL('./dist/public-download', import.meta.url)),
    emptyOutDir: true,
  },
});
