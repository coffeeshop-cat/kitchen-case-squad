import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    proxy: {
      '/health': 'http://127.0.0.1:8765',
      '/cases': 'http://127.0.0.1:8765'
    }
  },
  build: {
    outDir: 'dist'
  }
});
