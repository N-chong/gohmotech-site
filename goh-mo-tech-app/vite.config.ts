/// <reference types="vitest" />

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    vue()
  ],
  build: {
    // Ionic's Vue integration is emitted as one framework module (~1.1 MB
    // minified, ~231 KB gzip). App pages remain route-split; forcing this
    // module into arbitrary pieces adds requests without reducing its payload.
    chunkSizeWarningLimit: 1200,
    // Ionic's utility stylesheet uses :host-context for RTL helpers. Vite 8's
    // Lightning CSS minifier warns on that valid Ionic syntax; esbuild keeps it.
    cssMinify: 'esbuild',
  },
  resolve: {
    alias: {
      '@': import.meta.dirname + '/src',
    },
  },
  test: {
    globals: true,
    environment: 'jsdom'
  }
})
