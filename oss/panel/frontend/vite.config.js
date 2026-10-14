import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Strip type="module" from the script tag: the bundle is IIFE, and jsdom
// (used by our smoke tests) does not execute module scripts.
function noModuleScript() {
  return {
    name: 'no-module-script',
    transformIndexHtml(html) {
      return html.replace(' type="module" crossorigin', '')
    },
  }
}

export default defineConfig({
  plugins: [vue(), noModuleScript()],
  base: './',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    assetsDir: 'assets',
    // IIFE (not ESM): the panel must also run under jsdom smoke tests,
    // which do not execute <script type="module">.
    rollupOptions: { output: { format: 'iife', inlineDynamicImports: true } },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8080',
      '/sub': 'http://127.0.0.1:8080',
    },
  },
})
